"""Local a_bogus signing from a verified, same-session merchant SDK sample.

Algorithm adapted from cv-cat/catbus src/platforms/douyin/web/sign.ts.
https://github.com/cv-cat/catbus

MIT License, Copyright (c) 2026 cv-cat

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from functools import reduce
from operator import xor
from urllib.parse import parse_qsl, unquote, urlsplit

from commerce_api.core.errors import ContextRequired

SALT = b"dhzx"
EPOCH = 1721836800000
S3 = "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe"
S4 = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
PERM = (34, 44, 56, 61, 73, 29, 70, 45, 35, 49, 38, 66, 51, 68, 28, 48, 64, 47,
    30, 71, 26, 55, 31, 69, 59, 40, 62, 63, 27, 72, 41, 74, 57, 52, 42, 39,
    33, 67, 53, 43, 65, 46, 36, 24, 60, 32, 79, 80, 84, 85)
CHECK = (24, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 38, 39, 40, 41, 42, 43,
    44, 45, 46, 47, 48, 49, 51, 52, 53, 55, 56, 57, 59, 60, 61, 62, 63, 64,
    65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 79, 80, 84, 85)


def sm3(value: bytes) -> bytes:
    # cryptography is already an explicit project dependency and provides SM3
    # on Windows even when the interpreter's hashlib provider omits it.
    from cryptography.hazmat.primitives import hashes
    digest = hashes.Hash(hashes.SM3())
    digest.update(value)
    return digest.finalize()


def digest(value: bytes) -> bytes:
    return sm3(sm3(value + SALT))


def rc4(key, data):
    state = list(reversed(range(256)))
    j = 0
    for i in range(256):
        j = (j * state[i] + j + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]
    i = j = 0
    out = []
    for value in data:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        out.append(value ^ state[(state[i] + state[j]) % 256])
    return out


def encode(values, alphabet):
    return base64.b64encode(bytes(values)).decode().translate(str.maketrans(BASE64, alphabet))


def decode(value, alphabet):
    return base64.b64decode(value.translate(str.maketrans(alphabet, BASE64)), validate=True)


def blend(c0, c1, r0, r1):
    return [(r0 & 170) | (c0 & 85), (r0 & 85) | (c0 & 170),
        (r1 & 170) | (c1 & 85), (r1 & 85) | (c1 & 170)]


def expand(values, random):
    output = []
    for offset in range(0, len(values), 3):
        group = values[offset:offset + 3]
        if len(group) == 3:
            r = int(random() * 1000) & 255
            a, b, c = group
            output.extend(((r & 145) | (a & 110), (r & 66) | (b & 189),
                (r & 44) | (c & 211), (a & 145) | (b & 66) | (c & 44)))
        else:
            output.extend(group)
    return output


def unexpand(values):
    output = []
    for offset in range(0, len(values), 4):
        group = values[offset:offset + 4]
        if len(group) == 4:
            a, b, c, tail = group
            output.extend(((a & 110) | (tail & 145), (b & 189) | (tail & 66),
                (c & 211) | (tail & 44)))
        elif len(group) <= 2:
            output.extend(group)
        else:
            raise ValueError("Unsupported signing layout")
    return output


def strip_signature(query: str) -> str:
    # Keep the exact encoded byte order; parse_qsl/urlencode can turn %20 into
    # '+' and invalidate the digest of an otherwise identical request.
    return "&".join(part for part in query.split("&") if unquote(part.partition("=")[0]) != "a_bogus")


def escaped(value, index, reserved, fallback, force):
    selected = value[index] if index < len(value) else fallback
    while selected == reserved:
        index += 1
        selected = value[index] if index < len(value) else fallback
    return reserved if force else selected


def ua_digest(user_agent, sdk_version, sdk_minor):
    values = rc4([sdk_version // 256, sdk_version % 256, sdk_minor % 256], [ord(c) for c in user_agent.strip()])
    return sm3(encode(values, S3).encode())


def _number(fields, offset, size):
    return sum(fields[offset + i] << (i * 8) for i in range(size))


def _put(fields, offset, value, size):
    fields.update((offset + i, (value >> (i * 8)) & 255) for i in range(size))


def derive_material(url: str, user_agent: str, body: bytes = b"") -> dict:
    """Verify sample digests before accepting its public SDK/device parameters.

    The captured signature, request timestamp and session tokens are never
    returned as signing material. Future requests use fresh time and randomness.
    """
    try:
        parts = urlsplit(url)
        values = [value for key, value in parse_qsl(parts.query) if key == "a_bogus"]
        if parts.hostname != "fxg.jinritemai.com" or len(values) != 1:
            raise ValueError()
        raw = decode(values[0], S4)
        if len(raw) < 80:
            raise ValueError()
        plain = rc4([211], raw[4:])
        packed = unexpand(plain[8:])
        fields = dict(zip(PERM, packed[:len(PERM)], strict=True))
        geometry_length, tail_length = _number(fields, 79, 2), _number(fields, 84, 2)
        if len(packed) != len(PERM) + geometry_length + tail_length + 1 or fields[24] != 41 or fields[66] != 3:
            raise ValueError()
        if reduce(xor, plain[:8] + [fields[key] for key in CHECK], 0) != packed[-1]:
            raise ValueError()
        sdk_version, sdk_minor = _number(fields, 35, 2), _number(fields, 44, 4)
        flags = _number(fields, 38, 2)
        query_hash = digest(strip_signature(parts.query).encode())
        body_hash = digest(body)
        browser_hash = ua_digest(user_agent, sdk_version, sdk_minor)
        actual = [fields[key] for key in (48, 49, 51, 52, 53, 55, 56, 57, 59)]
        expected = [query_hash[9], query_hash[18], escaped(query_hash, 3, 11, 12, flags & 2),
            body_hash[10], body_hash[19], escaped(body_hash, 4, 8, 9, flags & 4),
            browser_hash[11], browser_hash[21], escaped(browser_hash, 5, 12, 13, flags & 8)]
        if actual != expected:
            raise ValueError()
        geometry = bytes(packed[len(PERM):len(PERM) + geometry_length]).decode("ascii")
        if not geometry.endswith("|Win32") or len(geometry) > 180:
            raise ValueError()
        tail = bytes(packed[len(PERM) + geometry_length:-1]).decode("ascii")
        offset = (raw[2] & 170) | (raw[3] & 85)
        browser_base = next((value for value in (0, 40, 81, 125, 170, 210) if value <= offset < value + 40), None)
        if browser_base is None or not tail.endswith(","):
            raise ValueError()
        material = {"version": 1, "sdk_version": sdk_version, "sdk_minor": sdk_minor,
            "aid": _number(fields, 71, 4), "page_id": _number(fields, 67, 4),
            "environment_flags": flags, "sdk_flags": [fields[key] for key in (40, 41, 42)],
            "geometry": geometry, "browser_base": browser_base, "timing_byte": fields[28],
            "tail_delta": (int(tail[:-1]) - fields[29]) & 255,
            "user_agent_sha256": hashlib.sha256(user_agent.encode()).hexdigest()}
        if material["aid"] != 4272 or sdk_version <= 0 or not 0 <= sdk_minor <= 255:
            raise ValueError()
        return material
    except (ValueError, IndexError, KeyError, TypeError, UnicodeError):
        raise ContextRequired("抖店订单签名样本尚未通过请求、正文及浏览器身份校验，请显式认证更新上下文", stage="context") from None


class Signer:
    def __init__(self, material, user_agent, *, clock=None, random=None):
        if material.get("version") != 1 or material.get("user_agent_sha256") != hashlib.sha256(user_agent.encode()).hexdigest():
            raise ContextRequired("抖店签名材料与当前浏览器身份不匹配", stage="context")
        self.material, self.user_agent = material, user_agent
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.random = random or secrets.SystemRandom().random
        self.counter = 2

    def sign(self, query: str, body: bytes = b"") -> str:
        material, fields = self.material, {}
        stamp = int(self.clock())
        self.counter += 1
        query_hash, body_hash = digest(strip_signature(query).encode()), digest(body)
        browser_hash = ua_digest(self.user_agent, material["sdk_version"], material["sdk_minor"])
        flags = material["environment_flags"]
        fields.update({24: 41, 26: int((stamp - EPOCH) / 1209600000) & 255,
            27: 3 if self.counter > 10745 else 4 if self.counter > 1283 else 5 if self.counter > 139 else 6,
            28: material["timing_byte"], 40: material["sdk_flags"][0], 41: material["sdk_flags"][1],
            42: material["sdk_flags"][2], 43: 0, 48: query_hash[9], 49: query_hash[18],
            51: escaped(query_hash, 3, 11, 12, flags & 2), 52: body_hash[10], 53: body_hash[19],
            55: escaped(body_hash, 4, 8, 9, flags & 4), 56: browser_hash[11], 57: browser_hash[21],
            59: escaped(browser_hash, 5, 12, 13, flags & 8), 66: 3})
        for offset, value, size in ((29, stamp, 6), (35, material["sdk_version"], 2), (38, flags, 2),
                (44, material["sdk_minor"], 4), (60, stamp - 1, 6),
                (67, material["page_id"], 4), (71, material["aid"], 4)):
            _put(fields, offset, value, size)
        geometry = material["geometry"].encode("ascii")
        tail = f"{(stamp + material['tail_delta']) & 255},".encode()
        _put(fields, 79, len(geometry), 2)
        _put(fields, 84, len(tail), 2)
        r = int(self.random() * 65535)
        prefix = blend(1, 0, r & 255, (r >> 8) & 255)
        self.random()
        r = self.random()
        if flags & 64:
            check = int(r * 109)
            check += 110 + (check % 2)
        else:
            check = int(r * 240)
            check = check + (check % 2) + 1 if check > 109 else check
        permission = (int(self.random() * 255) & 77) | 2 | 16 | 32 | 128
        prefix += blend(1, 0, check, permission)
        checksum = reduce(xor, prefix + [fields[key] for key in CHECK], 0)
        packed = [fields[key] for key in PERM] + list(geometry) + list(tail) + [checksum]
        header = blend(3, 82, int(self.random() * 65535) & 255,
            int(self.random() * 40) + material["browser_base"])
        return encode(header + rc4([211], prefix + expand(packed, self.random)), S4)
