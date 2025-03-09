# login.py
import json
import os
import time
import hashlib
import base64
import hmac
import uuid
import requests
from email.utils import formatdate
from common.log import logger

class LoginHandler:
    def __init__(self, config):
        self.config = config
        self.base_url = 'https://api-bj.wenxiaobai.com'
        self.secret_key = 'TkoWuEN8cpDJubb7Zfwxln16NQDZIc8z'

    def _get_web_id(self):
        """获取Web ID"""
        try:
            payload = {
                "app_id": 20001987,
                "url": "https://www.wenxiaobai.com/chat/tourist",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                "referer": "",
                "user_unique_id": ""
            }
            response = requests.post('https://gator.volces.com/webid', json=payload)
            if response.status_code == 200:
                data = response.json()
                if data.get('web_id'):
                    self.config['web_id'] = data['web_id']
                    return data['web_id']
        except Exception as e:
            logger.error(f"[WenXiaoBai] 获取Web ID失败: {str(e)}")
        return None

    def _generate_digest(self, content=''):
        """生成请求摘要"""
        if content:
            content_hash = hashlib.sha256(content.encode()).digest()
            return f"SHA-256={base64.b64encode(content_hash).decode()}"
        return 'SHA-256=47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='

    def _generate_signature(self, date_str, digest_str):
        """生成HMAC签名"""
        string_to_sign = f'x-date: {date_str}\ndigest: {digest_str}'
        signature = hmac.new(
            self.secret_key.encode(),
            string_to_sign.encode(),
            hashlib.sha1
        ).digest()
        return base64.b64encode(signature).decode()

    def get_headers(self, content=''):
        """生成通用请求头"""
        date_str = formatdate(timeval=time.time(), localtime=False, usegmt=True)
        digest_str = self._generate_digest(content)
        
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'cache-control': 'no-cache',
            'content-type': 'application/json',
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
            'x-yuanshi-appversioncode': '2.1.5',
            'x-yuanshi-appversionname': '2.8.0',
            'x-yuanshi-channel': 'browser',
            'x-yuanshi-devicemode': 'Chrome',
            'x-yuanshi-deviceos': '129',
            'x-yuanshi-locale': 'zh',
            'x-yuanshi-platform': 'web',
            'x-yuanshi-timezone': 'Asia/Shanghai'
        }
        
        signature = self._generate_signature(date_str, digest_str)
        headers['authorization'] = f'hmac username="web.1.0.beta", algorithm="hmac-sha1", headers="x-date digest", signature="{signature}"'
        
        if self.config.get('token'):
            headers['x-yuanshi-authorization'] = f"Bearer {self.config['token']}"
            
        if self.config.get('device_id'):
            headers['x-yuanshi-deviceid'] = self.config['device_id']
            
        return headers

    def send_code(self, phone):
        """发送验证码"""
        # 先获取 web_id
        if not self.config.get('web_id'):
            self._get_web_id()
            
        url = f"{self.base_url}/api/v1.0/user/codes"  # 修正URL
        data = {
            "phone": phone,
            "type": "login"
        }
        
        try:
            headers = self.get_headers(json.dumps(data))
            response = requests.post(url, json=data, headers=headers)
            response_data = response.json()
            
            logger.info(f"[WenXiaoBai] 发送验证码响应: {response_data}")
            
            if response.status_code in [200, 201]:
                return response_data
            else:
                logger.error(f"[WenXiaoBai] 发送验证码失败，状态码: {response.status_code}，响应: {response_data}")
                return response_data
                
        except Exception as e:
            logger.error(f"[WenXiaoBai] 发送验证码请求异常: {str(e)}")
            return {"code": -1, "msg": f"请求异常: {str(e)}"}

    def do_login(self, phone, code):
        """执行登录"""
        # 生成设备ID
        timestamp = int(time.time() * 1000)
        rand_str = base64.b64encode(os.urandom(8)).decode()[:6]
        device_id = f"{hashlib.md5(str(timestamp).encode()).hexdigest()}_{timestamp}_{rand_str}"
        
        url = f"{self.base_url}/api/v1.0/user/sessions"
        data = {
            "phone": phone,
            "code": code,
            "deviceId": device_id,
            "device": "Chrome",
            "client": "web",
            "extraInfo": {"url": "https://www.wenxiaobai.com/chat/tourist"}
        }
        
        try:
            headers = self.get_headers(json.dumps(data))
            response = requests.post(url, json=data, headers=headers)
            
            if response.status_code in [200, 201]:
                result = response.json()
                if result.get("code") == 0:
                    user_data = result['data'].get('user', {})
                    token = result['data'].get('token', '')
                    
                    if user_data and token:
                        self.config.update({
                            'token': token,
                            'device_id': device_id,
                            'user_id': str(user_data['id']),
                            'phone': phone
                        })
                        logger.info(f"[WenXiaoBai] 登录成功，用户ID: {user_data['id']}")
                        return True
                    else:
                        logger.error("[WenXiaoBai] 响应中缺少用户信息或token")
                else:
                    logger.error(f"[WenXiaoBai] 登录失败: {result.get('msg', '未知错误')}")
            return False
        except Exception as e:
            logger.error(f"[WenXiaoBai] 登录失败: {str(e)}")
            return False