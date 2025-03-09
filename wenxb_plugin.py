import os
import json
import time
import re
import uuid
import hashlib
import base64
import requests
import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from plugins import *
from .apiclient import ApiClient
from .login import LoginHandler
import random

@plugins.register(
    name="WenXiaoBai",
    desire_priority=0,
    hidden=False,
    desc="基于问小白API的智能对话插件，支持对话和搜索功能",
    version="1.0",
    author="lanvent",
)
class WenXiaoBaiPlugin(Plugin):
    def __init__(self):
        super().__init__()
        try:
            # 加载配置
            self.config = super().load_config()
            if not self.config:
                self.config = self._load_config_template()
                
            # 初始化API客户端和登录处理器
            self.api_client = ApiClient(self.config)
            self.login_handler = LoginHandler(self.config)
            
            # 会话状态
            self.last_chat_time = 0
            self.turn_index = 0
            self.conversation_cooldown = 180  # 3分钟超时
            
            # 引用链接清理正则表达式
            self.ref_pattern = re.compile(r'\[\d+\](?:\(@ref\))?')
            
            # 登录状态
            self._login_state = None
            self._phone_number = None
            
            # 识图状态管理
            self.waiting_for_image = {}  # 用户等待图片状态
            self.image_queries = {}  # 存储用户的识图问题
            
            # 注册事件处理器
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            
            logger.info("[WenXiaoBai] Plugin initialized")
        except Exception as e:
            logger.error(f"[WenXiaoBai] 初始化异常: {e}")
            raise Exception("[WenXiaoBai] init failed, ignore")

    def _load_config_template(self):
        """加载配置模板"""
        try:
            plugin_config_path = os.path.join(self.path, "config.json.template")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return self._create_default_config()
        except Exception as e:
            logger.error(f"[WenXiaoBai] 加载配置模板失败: {str(e)}")
            return self._create_default_config()

    def _create_default_config(self):
        """创建默认配置"""
        return {
            "token": "",
            "device_id": "",
            "conversation_id": "",
            "user_id": "",
            "web_id": ""
        }

    def get_help_text(self, **kwargs):
        """返回插件帮助信息"""
        help_text = (
            "问小白插件使用说明：\n"
            "1. 对话功能：以'小白'开头，例如：\n"
            "   小白 今天天气怎么样？\n"
            "2. 搜索功能：以'小白搜索'开头，例如：\n"
            "   小白搜索 广州天气\n"
            "3. 首次使用需要登录，会自动提示登录流程\n"
        )
        return help_text

    def on_handle_context(self, e_context: EventContext):
        """处理上下文事件"""
        if e_context["context"].type not in [ContextType.TEXT, ContextType.IMAGE]:
            return
            
        content = e_context["context"].content.strip()
        msg: ChatMessage = e_context["context"]["msg"]
        
        # 获取用户ID
        user_id = getattr(msg, "from_user_id", None) or getattr(msg, "other_user_id", None)
        
        # 如果在登录状态，优先处理登录流程，不检查其他命令
        if self._login_state:
            # 处理手机号输入
            if self._login_state == 'waiting_phone':
                # 去除可能的空格
                content = content.strip()
                if re.match(r'^1[3-9]\d{9}$', content):
                    try:
                        sms_response = self.login_handler.send_code(content)
                        if sms_response and sms_response.get('code') == 0:
                            self._phone_number = content  # 只在内存中临时保存
                            self._login_state = 'waiting_code'
                            reply = Reply()
                            reply.type = ReplyType.TEXT
                            reply.content = "验证码已发送，请输入验证码："
                            e_context["reply"] = reply
                            e_context.action = EventAction.BREAK_PASS
                            return
                        else:
                            error_msg = sms_response.get('msg', '未知错误')
                            logger.error(f"[WenXiaoBai] 发送验证码失败: {error_msg}")
                            reply = Reply()
                            reply.type = ReplyType.TEXT
                            reply.content = f"发送验证码失败: {error_msg}\n请重新输入手机号："
                            e_context["reply"] = reply
                            e_context.action = EventAction.BREAK_PASS
                            return
                    except Exception as e:
                        logger.error(f"[WenXiaoBai] 发送验证码失败: {str(e)}")
                        reply = Reply()
                        reply.type = ReplyType.TEXT
                        reply.content = f"发送验证码失败: {str(e)}\n请重新输入手机号："
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS
                        return
                        
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "请输入正确的手机号（11位数字）："
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
                
            # 处理验证码输入
            elif self._login_state == 'waiting_code':
                try:
                    login_response = self.login_handler.do_login(self._phone_number, content)
                    if login_response:
                        # 登录成功后清除手机号
                        self._phone_number = None
                        self._login_state = None
                        self.save_config()
                        reply = Reply()
                        reply.type = ReplyType.TEXT
                        reply.content = "登录成功！请重新发送您的问题。"
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS
                        return
                    else:
                        reply = Reply()
                        reply.type = ReplyType.TEXT
                        reply.content = "验证码错误或已过期，请重新输入："
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS
                        return
                except Exception as e:
                    logger.error(f"[WenXiaoBai] 登录失败: {str(e)}")
                    reply = Reply()
                    reply.type = ReplyType.TEXT
                    reply.content = f"登录失败: {str(e)}"
                    e_context["reply"] = reply
                    e_context.action = EventAction.BREAK_PASS
                    return
            
            # 如果在登录状态但不是上述两种情况，继续等待正确输入
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = "请输入正确的验证信息"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
            
        # 处理图片消息
        if e_context["context"].type == ContextType.IMAGE and user_id in self.waiting_for_image:
            try:
                # 获取图片数据
                image_data = self._get_image_data(e_context["context"])
                if not image_data:
                    e_context["reply"] = Reply(ReplyType.ERROR, "获取图片失败，请重试")
                    e_context.action = EventAction.BREAK_PASS
                    return
                
                # 发送等待消息
                wait_reply = Reply(ReplyType.TEXT, "正在处理图片，请稍候...")
                e_context["channel"].send(wait_reply, e_context["context"])
                
                # 上传图片
                image_info = self._upload_image(image_data)
                if not image_info:
                    e_context["reply"] = Reply(ReplyType.ERROR, "上传图片失败，请重试")
                    e_context.action = EventAction.BREAK_PASS
                    return
                
                # 获取用户的问题
                query = self.image_queries.get(user_id, "")
                
                # 发送带图片的对话请求
                response = self._chat_with_image(query, image_info)
                
                # 发送回复
                reply = Reply(ReplyType.TEXT, response)
                e_context["reply"] = reply
                
            except Exception as e:
                logger.error(f"[WenXiaoBai] 处理图片失败: {e}")
                e_context["reply"] = Reply(ReplyType.ERROR, f"处理失败: {str(e)}")
                
            finally:
                # 清理状态
                self.waiting_for_image.pop(user_id, None)
                self.image_queries.pop(user_id, None)
                
            e_context.action = EventAction.BREAK_PASS
            return
            
        # 检查命令类型
        chat_match = re.match(r"^小白\s*(.*?)$", content)
        search_match = re.match(r"^小白搜索\s*(.*?)$", content)
        image_match = re.match(r"^小白生图\s*(.*?)(?:-([^-]+))?(?:-(\d+:\d+))?$", content)
        vision_match = re.match(r"^小白识图\s*(.*?)$", content)
        
        if not any([chat_match, search_match, image_match, vision_match]):
            return
            
        # 如果未登录，启动登录流程
        if not self.config.get('token'):
            if not self._login_state:
                self._login_state = 'waiting_phone'
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "首次使用需要登录\n请输入手机号码："
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            # 处理手机号输入
            if self._login_state == 'waiting_phone':
                # 去除可能的空格
                content = content.strip()
                if re.match(r'^1[3-9]\d{9}$', content):
                    try:
                        sms_response = self.login_handler.send_code(content)
                        if sms_response and sms_response.get('code') == 0:
                            self._phone_number = content  # 只在内存中临时保存
                            self._login_state = 'waiting_code'
                            reply = Reply()
                            reply.type = ReplyType.TEXT
                            reply.content = "验证码已发送，请输入验证码："
                            e_context["reply"] = reply
                            e_context.action = EventAction.BREAK_PASS
                            return
                        else:
                            error_msg = sms_response.get('msg', '未知错误')
                            logger.error(f"[WenXiaoBai] 发送验证码失败: {error_msg}")
                            reply = Reply()
                            reply.type = ReplyType.TEXT
                            reply.content = f"发送验证码失败: {error_msg}\n请重新输入手机号："
                            e_context["reply"] = reply
                            e_context.action = EventAction.BREAK_PASS
                            return
                    except Exception as e:
                        logger.error(f"[WenXiaoBai] 发送验证码失败: {str(e)}")
                        reply = Reply()
                        reply.type = ReplyType.TEXT
                        reply.content = f"发送验证码失败: {str(e)}\n请重新输入手机号："
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS
                        return
                        
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "请输入正确的手机号（11位数字）："
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
                
            # 处理验证码输入
            elif self._login_state == 'waiting_code':
                try:
                    login_response = self.login_handler.do_login(self._phone_number, content)
                    if login_response:
                        # 登录成功后清除手机号
                        self._phone_number = None
                        self._login_state = None
                        self.save_config()
                        reply = Reply()
                        reply.type = ReplyType.TEXT
                        reply.content = "登录成功！请重新发送您的问题。"
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS
                        return
                    else:
                        reply = Reply()
                        reply.type = ReplyType.TEXT
                        reply.content = "验证码错误或已过期，请重新输入："
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS
                        return
                except Exception as e:
                    logger.error(f"[WenXiaoBai] 登录失败: {str(e)}")
                    reply = Reply()
                    reply.type = ReplyType.TEXT
                    reply.content = f"登录失败: {str(e)}"
                    e_context["reply"] = reply
                    e_context.action = EventAction.BREAK_PASS
                    return
        
        # 处理各种请求
        try:
            if vision_match:  # 处理识图命令
                query = vision_match.group(1).strip()
                if not query:
                    e_context["reply"] = Reply(ReplyType.ERROR, "请在命令后输入问题，例如：小白识图 这个热量有多少")
                    e_context.action = EventAction.BREAK_PASS
                    return
                
                # 记录用户状态和问题
                if user_id:
                    self.waiting_for_image[user_id] = True
                    self.image_queries[user_id] = query
                    e_context["reply"] = Reply(ReplyType.TEXT, "请发送需要识别的图片")
                    e_context.action = EventAction.BREAK_PASS
                    return
                else:
                    e_context["reply"] = Reply(ReplyType.ERROR, "无法获取用户ID")
                    e_context.action = EventAction.BREAK_PASS
                    return
                    
            elif image_match:
                # 解析生图参数
                prompt = image_match.group(1).strip()
                style = image_match.group(2) or "电影写真"  # 默认风格
                size = image_match.group(3) or "16:9"      # 默认比例
                
                # 发送等待消息
                wait_reply = Reply(ReplyType.TEXT, "正在生成图片，请稍候...")
                e_context["channel"].send(wait_reply, e_context["context"])
                
                # 发送生图请求
                response = self.chat_image(prompt, style, size)
                if isinstance(response, list) and len(response) == 2:
                    prompt_reply, img_reply = response
                    
                    # 先发送提示词
                    if prompt_reply and prompt_reply.content:
                        e_context["channel"].send(prompt_reply, e_context["context"])
                        
                    # 等待提示词发送完成
                    time.sleep(1)
                    
                    # 再发送图片
                    if img_reply and img_reply.content:
                        e_context["channel"].send(img_reply, e_context["context"])
                    
                    # 设置事件动作为 BREAK_PASS，表示事件处理完成
                    e_context.action = EventAction.BREAK_PASS
                else:
                    # 处理错误情况
                    error_reply = Reply()
                    error_reply.type = ReplyType.ERROR
                    error_reply.content = response if isinstance(response, str) else "生成失败"
                    e_context["reply"] = error_reply
                    e_context.action = EventAction.BREAK_PASS
                
            elif search_match:
                query = search_match.group(1).strip()
                response = self.chat(query, use_search=True)
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = response
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                
            else:
                query = chat_match.group(1).strip()
                response = self.chat(query)
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = response
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
            
        except Exception as e:
            logger.error(f"[WenXiaoBai] 请求处理失败: {str(e)}")
            reply = Reply()
            reply.type = ReplyType.ERROR
            reply.content = f"请求处理失败: {str(e)}"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS

    def start_conversation(self):
        """开始新会话"""
        if not self.config.get('user_id'):
            logger.error("[WenXiaoBai] 缺少用户ID，请先登录")
            return False
        
        url = f"{self.api_client.base_url}/api/v1.0/core/conversations/users/{self.config['user_id']}/bots/200006/conversation"
        response = self.api_client.post(url, {"visitorId": self.config['device_id']})
        
        if response and response.get('code') == 0:
            self.config['conversation_id'] = response['data']
            self.save_config()
            logger.info(f"[WenXiaoBai] 新会话已创建: {self.config['conversation_id']}")
            return True
        logger.error(f"[WenXiaoBai] 会话创建失败: {response.get('msg') if response else '未知错误'}")
        return False

    def _process_response(self, response):
        """处理流式响应"""
        full_response = []
        thinking_time = ""
        last_index = -1
        response_started = False
        
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data:'):
                    try:
                        data = json.loads(decoded_line[5:])
                        if 'content' in data:
                            content = str(data['content'])
                            # 清理引用链接
                            content = self.ref_pattern.sub('', content)
                            content_index = data.get('contentIndex', 0)
                            
                            if not thinking_time and '已深度思考（用时' in content:
                                match = re.search(r'已深度思考（用时(.*?)）', content)
                                if match:
                                    thinking_time = match.group(1)
                                    response_started = True
                                    continue
                            
                            if '```' in content or '<' in content or '>' in content:
                                continue
                            
                            if response_started and content_index > last_index:
                                full_response.append((content_index, content))
                                last_index = content_index
                                
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.error(f"[WenXiaoBai] 响应解析错误: {str(e)}")
                        continue

        full_response.sort(key=lambda x: x[0])
        final_response = ''.join(content for _, content in full_response)
        
        # 最后再次清理所有引用标记
        final_response = self.ref_pattern.sub('', final_response).strip()
        if thinking_time:
            final_response = f"已深度思考（用时{thinking_time}）\n{final_response}"
        
        return final_response if final_response else "收到空响应"

    def chat(self, query, use_search=False):
        """发送聊天请求"""
        return self._chat_with_mode(query, mode="chat")

    def chat_image(self, prompt, style, size):
        """处理生图请求"""
        result = self._chat_with_mode(
            prompt, 
            mode="image",
            style=style,
            size=size
        )
        
        if isinstance(result, tuple):
            prompt_text, image_url = result
            
            # 创建提示词回复
            prompt_reply = Reply()
            prompt_reply.type = ReplyType.TEXT
            prompt_reply.content = prompt_text
            
            # 创建图片URL回复
            image_reply = Reply()
            image_reply.type = ReplyType.IMAGE_URL
            image_reply.content = image_url
            
            # 返回两个回复对象的列表
            return [prompt_reply, image_reply]
            
        return result

    def _chat_with_image(self, query, image_info):
        """发送带图片的对话请求"""
        return self._chat_with_mode(
            query, 
            mode="vision",
            image_info=image_info
        )

    def _check_and_refresh_conversation(self):
        """检查并刷新会话状态"""
        current_time = time.time()
        
        # 检查会话是否超时
        if (current_time - self.last_chat_time > self.conversation_cooldown 
            or not self.config.get('conversation_id')):
            # 创建新会话
            if not self.start_conversation():
                return False
            self.turn_index = 0
            
        # 更新最后活动时间
        self.last_chat_time = current_time
        return True

    def _get_capabilities(self, mode="chat"):
        """获取不同模式的能力配置"""
        base_capability = {
            "icon": "https://wy-static.wenxiaobai.com/bot-capability/prod/%E6%B7%B1%E5%BA%A6%E6%80%9D%E8%80%83.png",
            "title": "深度思考(R1)",
            "defaultQuery": "",
            "capability": "otherBot",
            "capabilityRang": 0,
            "minAppVersion": "",
            "botId": 200004,
            "botDesc": "深度回答这个问题（DeepSeek R1）",
            "selectedIcon": "https://wy-static.wenxiaobai.com/bot-capability/prod/%E6%B7%B1%E5%BA%A6%E6%80%9D%E8%80%83%E9%80%89%E4%B8%AD.png",
            "botIcon": "https://platform-dev-1319140468.cos.ap-nanjing.myqcloud.com/bot/avatar/2025/02/06/612cbff8-51e6-4c6a-8530-cb551bcfda56.webp",
            "exclusiveCapabilities": None,
            "defaultSelected": False,
            "defaultHidden": False,
            "key": "deep_think",
            "defaultPlaceholder": "",
            "isPromptMenu": False,
            "promptMenu": False,
            "_id": "deep_think"
        }
        
        capabilities = [base_capability]
        
        if mode == "chat":
            # 普通对话模式，添加联网搜索能力
            capabilities.append({
                "icon": "https://wy-static.wenxiaobai.com/bot-capability/prod/%E8%81%94%E7%BD%91%E6%90%9C%E7%B4%A2.png",
                "title": "联网搜索",
                "capability": "otherBot",
                "capabilityRang": 0,
                "botId": 200007,
                "key": "deep_search"
            })
        elif mode == "vision":
            # 识图模式，不添加联网搜索能力
            pass
        elif mode == "image":
            # 生图模式，添加生图能力
            capabilities.append({
                "icon": "https://wy-static.wenxiaobai.com/bot-capability/prod/%E5%9B%BE%E7%89%87%E7%94%9F%E6%88%902.png",
                "title": "推理生图",
                "defaultQuery": "",
                "capability": "otherBot",
                "capabilityRang": 2,
                "minAppVersion": "",
                "botId": 100002,
                "botDesc": "",
                "selectedIcon": "",
                "botIcon": "",
                "exclusiveCapabilities": ["file", "camera", "image", "deep_search"],
                "defaultSelected": True,
                "defaultHidden": False,
                "key": "imageGenerate",
                "defaultPlaceholder": "请输入图片的场景、主体、布局、情绪、氛围、风格等，如开启深度思考R1，会帮你智能扩写描述词",
                "isPromptMenu": True,
                "promptMenu": True,
                "_id": "imageGenerate"
            })
            
        return capabilities

    def _chat_with_mode(self, query, mode="chat", **kwargs):
        """统一的对话处理函数"""
        try:
            # 检查并刷新会话状态
            if not self._check_and_refresh_conversation():
                return "会话创建失败"
            
            # 构建基础请求数据
            chat_data = {
                "userId": int(self.config['user_id']),
                "botId": "200006",
                "botAlias": "custom",
                "isRetry": False,
                "breakingStrategy": 0,
                "isNewConversation": self.turn_index == 0,
                "mediaInfos": [],
                "turnIndex": self.turn_index,
                "rewriteQuery": "",
                "conversationId": self.config['conversation_id'],
                "capabilities": self._get_capabilities(mode),
                "attachmentInfo": {"url": {"infoList": []}},
                "inputWay": "proactive"
            }
            
            # 根据不同模式添加特定参数
            if mode == "vision" and "image_info" in kwargs:
                # 识图模式添加图片信息
                chat_data["query"] = query
                chat_data["pureQuery"] = query
                chat_data["mediaInfos"] = [{
                    "fileMd5": kwargs["image_info"]["fileMd5"],
                    "fileId": kwargs["image_info"]["fileId"]
                }]
            elif mode == "image":
                # 生图模式添加样式和尺寸
                style = kwargs.get("style", "电影写真")
                size = kwargs.get("size", "16:9")
                chat_data["query"] = f"风格「{style}」，{query}，尺寸「{size}」"
                chat_data["pureQuery"] = query
                chat_data["imageGenerate"] = {
                    "style": style,
                    "size": size
                }
            else:
                # 普通对话模式
                chat_data["query"] = query
                chat_data["pureQuery"] = query
            
            # 发送请求
            response = self.api_client.stream_post(
                f'{self.api_client.base_url}/api/v1.0/core/conversation/chat/v1',
                chat_data,
                is_chat=True
            )
            
            if response and response.status_code == 200:
                self.turn_index += 1
                
                # 根据模式处理响应
                if mode == "image":
                    return self._process_image_response(response)
                else:
                    return self._process_response(response)
                    
            return f"请求失败 (状态码: {getattr(response, 'status_code', '无响应')})"
            
        except Exception as e:
            logger.error(f"[WenXiaoBai] 对话请求失败: {str(e)}")
            return f"请求失败: {str(e)}"

    def _process_image_response(self, response):
        """处理生图响应"""
        prompt_parts = []
        image_url = None
        thinking_time = None
        is_collecting_prompt = False
        
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data:'):
                    try:
                        data = json.loads(decoded_line[5:])
                        content = data.get('content', '')
                        
                        # 检查是否开始收集提示词
                        if '「' in content:
                            is_collecting_prompt = True
                            content = content.replace('\n\n\n「', '')
                        
                        # 收集提示词内容
                        if is_collecting_prompt:
                            if '」' in content:
                                content = content.replace('」', '')
                                prompt_parts.append(content)
                                is_collecting_prompt = False
                            else:
                                prompt_parts.append(content)
                        
                        # 提取思考时间
                        if '<end>已深度思考（用时' in content:
                            thinking_match = re.search(r'已深度思考（用时(\d+)秒）', content)
                            if thinking_match:
                                thinking_time = thinking_match.group(1)
                        
                        # 提取图片URL
                        if 'content image_url' in content:
                            url_match = re.search(r'content image_url\s+(https?://[^\s\n`]+)', content)
                            if url_match:
                                image_url = url_match.group(1)
                                
                    except json.JSONDecodeError:
                        continue
        
        # 组装最终提示词
        final_prompt = ''.join(prompt_parts).strip()
        formatted_prompt = f"提示词：\n{final_prompt}"
        if thinking_time:
            formatted_prompt = f"已深度思考（用时{thinking_time}秒）\n{formatted_prompt}"
            
        if formatted_prompt and image_url:
            return formatted_prompt, image_url
            
        return "生成失败，未获取到完整响应"

    def save_config(self):
        """保存配置"""
        try:
            config_path = os.path.join(self.path, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"[WenXiaoBai] 配置保存失败: {str(e)}")

    def _handle_image_reply(self, e_context: EventContext):
        """处理图片回复的辅助函数"""
        try:
            if e_context["reply"].type == ReplyType.IMAGE_URL:
                logger.info(f"[WenXiaoBai] 发送图片: {e_context['reply'].content}")
            return e_context
        except Exception as e:
            logger.error(f"[WenXiaoBai] 处理图片回复失败: {str(e)}")
            return None

    def _get_image_data(self, context):
        """获取图片数据"""
        try:
            msg = context.kwargs.get("msg")
            content = context.content
            
            # 如果已经是二进制数据，直接返回
            if isinstance(content, bytes):
                return content
                
            # 统一的文件读取函数
            def read_file(file_path):
                try:
                    with open(file_path, "rb") as f:
                        return f.read()
                except Exception as e:
                    logger.error(f"[WenXiaoBai] 读取文件失败 {file_path}: {e}")
                    return None
            
            # 按优先级尝试不同的读取方式
            if isinstance(content, str):
                # 1. 如果是文件路径，直接读取
                if os.path.isfile(content):
                    data = read_file(content)
                    if data:
                        return data
                
                # 2. 如果是URL，尝试下载
                if content.startswith(("http://", "https://")):
                    try:
                        response = requests.get(content, timeout=30)
                        if response.status_code == 200:
                            return response.content
                    except Exception as e:
                        logger.error(f"[WenXiaoBai] 从URL下载失败: {e}")
            
            # 3. 尝试从msg.content读取
            if hasattr(msg, "content") and os.path.isfile(msg.content):
                data = read_file(msg.content)
                if data:
                    return data
            
            # 4. 如果文件未下载，尝试下载
            if hasattr(msg, "_prepare_fn") and not msg._prepared:
                try:
                    msg._prepare_fn()
                    msg._prepared = True
                    time.sleep(1)  # 等待文件准备完成
                    
                    if hasattr(msg, "content") and os.path.isfile(msg.content):
                        data = read_file(msg.content)
                        if data:
                            return data
                except Exception as e:
                    logger.error(f"[WenXiaoBai] 下载图片失败: {e}")
            
            return None
            
        except Exception as e:
            logger.error(f"[WenXiaoBai] 获取图片数据失败: {e}")
            return None

    def _upload_image(self, image_data):
        """上传图片到问小白服务器"""
        try:
            # 生成随机文件名
            filename = f"n_v{random.getrandbits(64):016x}.jpg"
            
            # 获取预签名URL
            pre_sign_data = {
                "fileName": filename
            }
            pre_sign_response = self.api_client.post("https://api-bj.wenxiaobai.com/api/v1.0/file/pre-sign", pre_sign_data)
            
            if not pre_sign_response or pre_sign_response.get("code") != 0:
                logger.error(f"[WenXiaoBai] 获取预签名URL失败: {pre_sign_response}")
                return None
                
            file_id = pre_sign_response["data"]["fileId"]
            pre_sign_url = pre_sign_response["data"]["preSignUrl"]
            
            # 上传图片到预签名URL
            headers = {
                "Content-Type": "image/jpeg"
            }
            upload_response = requests.put(pre_sign_url, data=image_data, headers=headers)
            
            if upload_response.status_code != 200:
                logger.error(f"[WenXiaoBai] 上传图片失败: {upload_response.status_code}")
                return None
                
            # 解析上传结果
            parse_data = {
                "fileId": file_id,
                "multimodalCapability": {}
            }
            
            # 轮询解析结果
            max_retries = 10
            for i in range(max_retries):
                parse_response = self.api_client.post("https://api-bj.wenxiaobai.com/api/v1.0/file/parse", parse_data)
                if parse_response and parse_response.get("code") == 0:
                    data = parse_response.get("data", {})
                    if data.get("parseState") == 2:  # 解析成功
                        return {
                            "fileId": file_id,
                            "fileMd5": data.get("fileMd5"),
                            "downloadUrl": data.get("downloadUrl")
                        }
                time.sleep(1)
                
            logger.error("[WenXiaoBai] 图片解析超时")
            return None
            
        except Exception as e:
            logger.error(f"[WenXiaoBai] 上传图片失败: {e}")
            return None 