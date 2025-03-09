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
            'cache-control': 'no-cache',
            'content-type': 'application/json; charset=utf-8',  # 确保UTF-8编码
            'origin': 'https://www.wenxiaobai.com',
            'pragma': 'no-cache',
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

    def post(self, url, data=None):
        """发送POST请求"""
        try:
            # 确保数据使用UTF-8编码
            json_data = json.dumps(data, ensure_ascii=False).encode('utf-8') if data else None
            json_str = json.dumps(data, ensure_ascii=False) if data else ''
            
            # 获取头部，包含认证信息
            headers = self.get_headers(json_str)
            
            response = self.session.post(
                url, 
                data=json_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API请求失败: {response.status_code} - {response.text}")
                return {"code": response.status_code, "msg": response.text}
        except UnicodeEncodeError as e:
            logger.error(f"编码错误: {e}")
            # 尝试降级处理
            try:
                # 使用ASCII编码但保留可打印字符
                data_str = json.dumps(data, ensure_ascii=True)
                # 获取头部
                headers = self.get_headers(data_str)
                response = self.session.post(url, data=data_str.encode('utf-8'), headers=headers, timeout=30)
                return response.json() if response.status_code == 200 else {"code": response.status_code, "msg": response.text}
            except Exception as fallback_e:
                logger.error(f"降级处理失败: {fallback_e}")
                return {"code": -1, "msg": f"请求编码错误: {str(e)}"}
        except Exception as e:
            logger.error(f"API请求异常: {str(e)}")
            return {"code": -1, "msg": str(e)}

    def stream_post(self, url, data=None, is_chat=False):
        """发送流式POST请求"""
        try:
            # 确保数据使用UTF-8编码
            json_data = json.dumps(data, ensure_ascii=False).encode('utf-8') if data else None
            json_str = json.dumps(data, ensure_ascii=False) if data else ''
            
            # 获取包含认证信息的头部
            headers = self.get_headers(json_str, is_chat)
            
            # 先发送心跳请求
            self._send_heartbeat()
            
            # 发送事件追踪
            if is_chat and data and 'query' in data:
                self._send_tracking_event(data['query'])
            
            response = self.session.post(
                url, 
                data=json_data,
                headers=headers,
                stream=True,
                timeout=120  # 增加超时时间
            )
            
            if response.status_code != 200:
                logger.error(f"流式API请求失败: {response.status_code} - {response.text}")
                
            return response
            
        except UnicodeEncodeError as e:
            logger.error(f"流式请求编码错误: {e}")
            # 尝试降级处理
            try:
                # 使用ASCII编码但保留可打印字符
                data_str = json.dumps(data, ensure_ascii=True)
                headers = self.get_headers(data_str, is_chat)
                return self.session.post(url, data=data_str.encode('utf-8'), headers=headers, stream=True, timeout=120)
            except Exception as fallback_e:
                logger.error(f"流式请求降级处理失败: {fallback_e}")
                return None
        except Exception as e:
            logger.error(f"流式API请求异常: {str(e)}")
            return None

    def _send_heartbeat(self):
        """发送心跳包"""
        try:
            url = f'{self.base_url}/api/v1.0/user/time/heartbeat'
            headers = {
                'accept': '*/*',
                'accept-language': 'zh-CN,zh;q=0.9',
                'content-length': '0',
                'origin': 'https://www.wenxiaobai.com',
                'priority': 'u=1, i',
                'referer': 'https://www.wenxiaobai.com/',
                'sec-ch-ua': '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
            }
            
            if token := self.config.get('token'):
                headers['x-yuanshi-authorization'] = f"Bearer {token}"
            if device_id := self.config.get('device_id'):
                headers['x-yuanshi-deviceid'] = device_id
                
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
                            "conversation_id": self.config.get('conversation_id', ''),
                            "turn_id": turn_id,
                            "content": message,
                            "sse_event": "begin",
                            "refer_page": "history",
                            "user_id": self.config.get('user_id', ''),
                            "bot_id": "200006",
                            "event_index": event_index + 1
                        }),
                        "local_time_ms": int(time.time() * 1000),
                        "session_id": session_id
                    },
                    {
                        "event": "chat_input_new_start_btn_click",
                        "params": json.dumps({
                            "page": "chat",
                            "area": "input",
                            "element": "new_start_btn",
                            "bhv_type": "click",
                            "is_new_start": 1,
                            "conversation_id": self.config.get('conversation_id', ''),
                            "is_active_new_start": 1,
                            "refer_page": "history",
                            "user_id": self.config.get('user_id', ''),
                            "bot_id": "200006",
                            "event_index": event_index
                        }),
                        "local_time_ms": int(time.time() * 1000) - 100,
                        "session_id": session_id
                    }
                ],
                "user": {
                    "user_unique_id": self.config.get('user_id', ''),
                    "web_id": self.config.get('web_id', '')
                },
                "header": {
                    "app_id": 20001987,
                    "os_name": "windows",
                    "os_version": "10",
                    "device_model": "Windows NT 10.0",
                    "language": "zh-CN",
                    "platform": "web",
                    "sdk_version": "5.1.9_feature_2",
                    "sdk_lib": "js",
                    "timezone": 8,
                    "tz_offset": -28800,
                    "resolution": "1280x720",
                    "browser": "Chrome",
                    "browser_version": "129.0.0.0",
                    "referrer": "https://www.wenxiaobai.com/chat/tourist",
                    "referrer_host": "www.wenxiaobai.com",
                    "width": 1280,
                    "height": 720,
                    "screen_width": 1280,
                    "screen_height": 720,
                    "tracer_data": "{\"$utm_from_url\":1}",
                    "custom": "{}"
                },
                "local_time": int(time.time()),
                "verbose": 1
            }]
            
            headers = {
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Connection': 'keep-alive',
                'Content-Type': 'application/json; charset=UTF-8',
                'Origin': 'https://www.wenxiaobai.com',
                'Referer': 'https://www.wenxiaobai.com/',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'cross-site',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
                'sec-ch-ua': '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }
            
            response = requests.post(url, headers=headers, json=data)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"[WenXiaoBai] 事件追踪失败: {str(e)}")
            return False