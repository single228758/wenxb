# apiclient.py
import json
import time
import hashlib
import hmac
import base64
import requests
import uuid
from email.utils import formatdate
from common.log import logger

class ApiClient:
    def __init__(self, config):
        self.base_url = 'https://api-bj.wenxiaobai.com'
        self.secret_key = 'TkoWuEN8cpDJubb7Zfwxln16NQDZIc8z'
        self.config = config
        self.session = requests.Session()  # 使用持久会话
        self.session.headers.update({'Connection': 'keep-alive'})

    def _generate_digest(self, content=''):
        """生成内容摘要"""
        if content:
            content_bytes = content.encode('utf-8') if isinstance(content, str) else content
            content_hash = hashlib.sha256(content_bytes).digest()
            return f"SHA-256={base64.b64encode(content_hash).decode()}"
        return 'SHA-256=47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='

    def _generate_signature(self, date_str, digest_str):
        """生成安全签名"""
        string_to_sign = f'x-date: {date_str}\ndigest: {digest_str}'
        signature = hmac.new(
            self.secret_key.encode(),
            string_to_sign.encode(),
            hashlib.sha1
        ).digest()
        return base64.b64encode(signature).decode()

    def get_headers(self, content='', is_chat=False):
        """生成请求头"""
        date_str = formatdate(timeval=time.time(), localtime=False, usegmt=True)
        digest_str = self._generate_digest(content)
      
        headers = {
            'accept': 'text/event-stream, text/event-stream' if is_chat else 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://www.wenxiaobai.com',
            'priority': 'u=1, i',
            'referer': 'https://www.wenxiaobai.com/',
            'sec-ch-ua': '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
            'x-date': date_str,
            'digest': digest_str,
            'x-yuanshi-appname': 'wenxiaobai',
            'x-yuanshi-appversioncode': '' if is_chat else '2.1.5',
            'x-yuanshi-appversionname': '3.1.0' if is_chat else '2.8.0',
            'x-yuanshi-channel': 'browser',
            'x-yuanshi-devicemode': 'Chrome',
            'x-yuanshi-deviceos': '129',
            'x-yuanshi-locale': 'zh',
            'x-yuanshi-platform': 'web',
            'x-yuanshi-timezone': 'Asia/Shanghai'
        }
      
        signature = self._generate_signature(date_str, digest_str)
        headers['authorization'] = f'hmac username="web.1.0.beta", algorithm="hmac-sha1", headers="x-date digest", signature="{signature}"'
      
        if token := self.config.get('token'):
            headers['x-yuanshi-authorization'] = f"Bearer {token}"
          
        if device_id := self.config.get('device_id'):
            headers['x-yuanshi-deviceid'] = device_id
          
        return headers

    def post(self, url, data):
        """发送POST请求"""
        try:
            # 如果是完整URL，直接使用；否则拼接base_url
            full_url = url if url.startswith('http') else f"{self.base_url}{url}"
            
            # 将数据转换为JSON字符串
            content = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            
            # 获取请求头
            headers = self.get_headers(content)
            
            # 发送请求
            response = requests.post(full_url, data=content, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"[WenXiaoBai] POST请求失败 [{url}]: HTTP {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"[WenXiaoBai] POST请求失败 [{url}]: {str(e)}")
            return None

    def stream_post(self, url, data, is_chat=False):
        """发送流式POST请求"""
        try:
            content = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            headers = self.get_headers(content, is_chat)
            return self.session.post(url, headers=headers, data=content, stream=True)
        except Exception as e:
            logger.error(f"[WenXiaoBai] 流式POST失败 [{url}]: {str(e)}")
            return None

    def _send_heartbeat(self):
        """发送心跳包"""
        try:
            url = f'{self.base_url}/api/v1.0/user/time/heartbeat'
            headers = self.get_headers()
            response = self.session.post(url, headers=headers)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"[WenXiaoBai] 心跳失败: {str(e)}")
            return False

    def _send_tracking_event(self, message):
        """发送追踪事件"""
        try:
            url = 'https://gator.volces.com/list'
            turn_id = f"newTurnId_{int(time.time() * 1000)}"
            event_index = int(time.time() * 1000) - 15000
            session_id = str(uuid.uuid4())
        
            data = [{
                "events": [
                    {
                        "event": "chat_sse_event",
                        "params": json.dumps({
                            "conversation_id": self.config['conversation_id'],
                            "turn_id": turn_id,
                            "content": message,
                            "sse_event": "begin",
                            "refer_page": "history",
                            "user_id": self.config['user_id'],
                            "bot_id": "200006",
                            "event_index": event_index + 1
                        }),
                        "local_time_ms": int(time.time() * 1000),
                        "session_id": session_id
                    }
                ],
                "user": {
                    "user_unique_id": self.config['user_id'],
                    "web_id": self.config.get('web_id', '')
                },
                "header": {
                    "app_id": 20001987,
                    "os_name": "windows",
                    "os_version": "10",
                    "device_model": "Windows NT 10.0",
                    "platform": "web",
                    "browser": "Chrome",
                    "browser_version": "129.0.0.0"
                }
            }]
        
            headers = {
                'Accept': '*/*',
                'Content-Type': 'application/json',
                'Origin': 'https://www.wenxiaobai.com',
                'Referer': 'https://www.wenxiaobai.com/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
            }
        
            response = requests.post(url, headers=headers, json=data)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"[WenXiaoBai] 事件追踪失败: {str(e)}")
            return False