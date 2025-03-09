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
import random

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

    def get_headers(self, content=''):
        """生成通用请求头"""
        date_str = formatdate(timeval=time.time(), localtime=False, usegmt=True)
        digest_str = self._generate_digest(content)
        
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'cache-control': 'no-cache',
            'content-type': 'application/json; charset=utf-8',
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

    def generate_device_id(self):
        """生成设备ID"""
        timestamp = int(time.time() * 1000)
        rand_str = base64.b64encode(os.urandom(8)).decode()[:6]
        device_id = f"{hashlib.md5(str(timestamp).encode()).hexdigest()}_{timestamp}_{rand_str}"
        return device_id

    def send_code(self, phone):
        """发送验证码"""
        try:
            # 获取Web ID (如果还没有)
            if not self.config.get('web_id'):
                self._get_web_id()
                
            # 生成设备ID (如果还没有)
            if not self.config.get('device_id'):
                self.config['device_id'] = self.generate_device_id()
                
            # 使用与原代码一致的URL
            code_url = f'{self.base_url}/api/v1.0/user/codes'
            data = {"phone": phone}
            
            # 获取认证头
            headers = self.get_headers(json.dumps(data))
            
            response = requests.post(code_url, headers=headers, json=data)
            
            if response.status_code == 200:
                result = response.json()
                # 返回完整响应以便调用者检查code字段
                return result
                
            logger.error(f"[WenXiaoBai] 发送验证码失败: {response.status_code} - {response.text}")
            return {"code": -1, "msg": f"请求失败 ({response.status_code})"}
        except Exception as e:
            logger.error(f"[WenXiaoBai] 发送验证码异常: {str(e)}")
            return {"code": -1, "msg": str(e)}

    def do_login(self, phone, code):
        """登录验证"""
        try:
            # 使用与原代码一致的URL和参数
            login_url = f'{self.base_url}/api/v1.0/user/sessions'
            login_data = {
                "phone": phone,
                "code": code,
                "deviceId": self.config['device_id'],
                "device": "Chrome",
                "client": "web",
                "extraInfo": {"url": "https://www.wenxiaobai.com/chat/tourist"}
            }
                
            # 获取认证头
            headers = self.get_headers(json.dumps(login_data))
            
            response = requests.post(login_url, headers=headers, json=login_data)
            
            if response.status_code in [200, 201]:
                result = response.json()
                if result.get('code') == 0:
                    user_data = result['data'].get('user', {})
                    token = result['data'].get('token', '')
                    
                    if user_data and token:
                        self.config.update({
                            'token': token,
                            'user_id': str(user_data['id'])
                        })
                        
                        # 确保不保存手机号到配置文件
                        if 'phone' in self.config:
                            del self.config['phone']
                        
                        self._save_config()
                        logger.info(f"[WenXiaoBai] 登录成功: 用户ID={user_data['id']}")
                        return True
                    else:
                        logger.error("[WenXiaoBai] 响应中缺少用户信息或token")
                else:
                    logger.error(f"[WenXiaoBai] 登录失败: {result.get('msg', '未知错误')}")
            else:
                logger.error(f"[WenXiaoBai] 登录请求失败: {response.status_code} - {response.text}")
                
            return False
            
        except Exception as e:
            logger.error(f"[WenXiaoBai] 登录异常: {str(e)}")
            return False

    def _save_config(self):
        """保存配置"""
        try:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"[WenXiaoBai] 配置保存失败: {str(e)}")