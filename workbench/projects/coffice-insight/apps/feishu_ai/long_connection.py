from __future__ import annotations

import json
import threading
from datetime import datetime, timezone


class FeishuLongConnectionManager:
    """官方lark-oapi SDK长连接适配；SDK负责鉴权、心跳和重连。"""
    def __init__(self,service):
        self.service=service; self.clients=[]; self.threads=[]
        self._lock=threading.Lock(); self._states={}

    def start(self,configs):
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        except ImportError as exc:
            for config in configs:
                self._set_state(config["config_code"],"failed","lark_oapi_not_installed")
            return
        for config in configs:
            config_code=config["config_code"]
            try:
                def handler(data: P2ImMessageReceiveV1, current=config):
                    raw=json.loads(lark.JSON.marshal(data))
                    self.service.receive_sdk(current,raw)
                dispatcher=(lark.EventDispatcherHandler.builder("","")
                            .register_p2_im_message_receive_v1(handler).build())
                client=lark.ws.Client(config["app_id"],self.service._decrypt(config,"app_secret"),
                                      event_handler=dispatcher,log_level=lark.LogLevel.WARNING)
            except Exception as exc:
                self._set_state(config_code,"failed",type(exc).__name__)
                continue
            def runner(current_client=client,current_code=config_code):
                self._set_state(current_code,"starting",None)
                try:
                    self._set_state(current_code,"started",None)
                    current_client.start()
                    self._set_state(current_code,"stopped",None)
                except Exception as exc:
                    self._set_state(current_code,"failed",type(exc).__name__)
            thread=threading.Thread(target=runner,name=f"feishu-ws-{config_code}",daemon=True)
            self.clients.append(client);self.threads.append(thread);thread.start()

    def status(self,config_code):
        with self._lock:
            return dict(self._states.get(config_code) or {"status":"not_started","error":None,"updated_at":None})

    def _set_state(self,config_code,status,error):
        with self._lock:
            self._states[config_code]={"status":status,"error":error,
                                       "updated_at":datetime.now(timezone.utc).isoformat()}

    def close(self):
        for client in self.clients:
            stop=getattr(client,"stop",None)
            if callable(stop):
                try:stop()
                except Exception:pass
        self.clients.clear();self.threads.clear()
