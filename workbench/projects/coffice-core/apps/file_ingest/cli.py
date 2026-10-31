"""Authenticated manual uploads using the same HTTP contract as the web UI."""
from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def load_env(path):
    # Process only. Never persist credentials or include them in arguments.
    allowed = {'INGEST_BASE_URL','INGEST_USERNAME','INGEST_PASSWORD'}
    if Path(path).is_file():
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() in allowed:
                os.environ.setdefault(key.strip(),value.strip().strip('\"\''))


class Client:
    def __init__(self, base, username, password):
        self.base = base.rstrip('/')
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ''
        result = self.call('POST','/api/auth/login',{'username':username,'password':password})
        self.csrf = result['csrf_token']

    def call(self, method, path, payload=None, *, body=None, content_type='application/json', key=None):
        headers = {'Content-Type':content_type}
        if self.csrf:
            headers['X-CSRF-Token'] = self.csrf
        if key:
            headers['Idempotency-Key'] = key
        if body is None and payload is not None:
            body = json.dumps(payload,ensure_ascii=False).encode()
        request = urllib.request.Request(self.base+path,data=body,headers=headers,method=method)
        with self.opener.open(request,timeout=180) as response:
            result = json.load(response)
        if result.get('code'):
            raise ValueError(result.get('message','请求失败'))
        return result['data']

    def upload(self, run_id, item, base_dir, index):
        path = (base_dir / item['path']).resolve()
        if not item.get('report_type') or not item.get('shop_code'):
            raise ValueError('每份文件必须显式指定report_type和标准shop_code')
        boundary = 'codex-ingest-' + uuid.uuid4().hex
        fields = {'client_file_id':str(item.get('client_file_id') or index), 'report_type':item['report_type'],
                  'shop_code':item['shop_code'], 'coverage':json.dumps(item.get('coverage',{}),ensure_ascii=False)}
        parts = []
        for key, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        filename = path.name.replace('"','').replace('\r','').replace('\n','')
        parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(),path.read_bytes(),f'\r\n--{boundary}--\r\n'.encode()]
        return self.call('POST',f'/api/ingest/runs/{run_id}/files',body=b''.join(parts),
                         content_type='multipart/form-data; boundary='+boundary,key=fields['client_file_id'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',default=str(Path(__file__).resolve().parents[2]/'.env'))
    parser.add_argument('--base-url')
    sub = parser.add_subparsers(dest='command',required=True)
    upload = sub.add_parser('upload')
    upload.add_argument('--manifest',required=True)
    upload.add_argument('--idempotency-key',required=True)
    upload.add_argument('--mode',choices=['fill_gaps','replace_range','refresh_only'],default='fill_gaps')
    upload.add_argument('--submit',action='store_true',help='仅补缺时预检通过后提交；范围替换请单独complete确认预检令牌')
    for command in ('preflight','complete','status','reuse'):
        child = sub.add_parser(command)
        child.add_argument('--run-id',required=True)
        if command=='complete':
            child.add_argument('--preflight-token',required=True)
        elif command=='preflight':
            child.add_argument('--declarations',help='JSON文件：import_mode和coverage或逐文件items声明')
        elif command=='reuse':
            child.add_argument('--idempotency-key',required=True)
    retry = sub.add_parser('retry')
    retry.add_argument('--task-id',required=True)
    retry.add_argument('--snapshot-policy',choices=['latest','replay'],default='latest')
    retry.add_argument('--confirm-replay-publish',action='store_true',help='明确确认原快照重放会替换当前指标；仅replay使用')
    args = parser.parse_args()
    load_env(args.env_file)
    try:
        if args.command=='retry' and args.snapshot_policy=='replay' and not args.confirm_replay_publish:
            raise ValueError('原快照重放会替换当前指标；确认后须显式提供 --confirm-replay-publish。普通补数据使用默认latest。')
        if args.command=='upload' and args.submit and args.mode=='replace_range':
            raise ValueError('范围替换须先upload查看预检，再用complete和对应令牌确认')
        username,password = os.getenv('INGEST_USERNAME'),os.getenv('INGEST_PASSWORD')
        if not username:
            username = input('用户名：')
        if not password:
            password = getpass.getpass('密码：')
        client = Client(args.base_url or os.getenv('INGEST_BASE_URL','http://127.0.0.1:8770'),username,password)
        if args.command in {'upload','preflight','complete','retry','reuse'} and client.call('GET','/api/ingest/health').get('ingest_coverage_version') != 1:
            raise ValueError('后端尚未加载文件采信功能，请重新启动后端服务')
        if args.command=='upload':
            manifest = Path(args.manifest).resolve()
            items = json.loads(manifest.read_text(encoding='utf-8-sig'))
            if not isinstance(items,list) or not items:
                raise ValueError('manifest必须为非空文件列表')
            run = client.call('POST','/api/ingest/runs',{'source':'manual','expected_file_count':len(items),
                'idempotency_key':args.idempotency_key,'import_mode':args.mode,'auto_refresh':True})
            run_id = run['run_id']
            if run['status'] != 'draft':
                result = client.call('GET',f'/api/ingest/runs/{run_id}')
            else:
                for i,item in enumerate(items):
                    client.upload(run_id,item,manifest.parent,i)
                result = client.call('POST',f'/api/ingest/runs/{run_id}/coverage-preflight',{})
                result['run_id'] = run_id
                if args.submit and not result['blocked']:
                    result = client.call('POST',f'/api/ingest/runs/{run_id}/complete',{'preflight_token':result['token']})
        elif args.command=='preflight':
            declarations=json.loads(Path(args.declarations).read_text(encoding='utf-8-sig')) if args.declarations else {}
            result = client.call('POST',f'/api/ingest/runs/{args.run_id}/coverage-preflight',declarations)
        elif args.command=='reuse':
            result = client.call('POST',f'/api/ingest/runs/{args.run_id}/reuse',{'idempotency_key':args.idempotency_key})
        elif args.command=='complete':
            result = client.call('POST',f'/api/ingest/runs/{args.run_id}/complete',{'preflight_token':args.preflight_token})
        elif args.command=='status':
            result = client.call('GET',f'/api/ingest/runs/{args.run_id}')
        else:
            result = client.call('POST',f'/api/etl/tasks/{args.task_id}/retry',{'snapshot_policy':args.snapshot_policy,
                'confirm_replay_publish':args.confirm_replay_publish})
        print(json.dumps(result,ensure_ascii=False,default=str,indent=2))
        return 3 if result.get('blocked') else 5 if result.get('run',{}).get('status')=='failed' else 0
    except urllib.error.HTTPError as exc:
        try:
            response = json.load(exc)
            message = response.get('message',f'HTTP {exc.code}')
            error_code = ((response.get('data') or {}).get('details') or {}).get('error_code')
        except (ValueError,AttributeError):
            message = f'HTTP {exc.code}'
            error_code = None
        print(json.dumps({'error':message,'status':exc.code,'error_code':error_code},ensure_ascii=False),file=sys.stderr)
        return 4 if exc.code in (401,403) else 3 if exc.code==409 else 2
    except (ValueError,OSError,KeyError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
