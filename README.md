# wenxb
dow插件，问小白r1，推理生图，识图功能

# 问小白插件 (WenXiaoBai Plugin)

这是一个基于问小白的对话插件，支持智能对话和AI搜索功能。

## 功能特点

- 支持智能对话和AI搜索
- 自动登录和会话管理
- 完整的错误处理机制
- 支持配置文件管理

## 安装方法

1. 将插件文件夹复制到 `plugins` 目录下
2. 安装依赖：
```bash
pip install -r requirements.txt
```

## 使用方法

### 基础对话
使用 "小白" 前缀进行对话：
```
小白 今天天气怎么样？
```

### AI搜索
使用 "小白搜索" 前缀进行搜索：
```
小白搜索 广州今天天气
```
### 推理生图
使用 "小白生图" 前缀进行推理生图：
```
小白生图 一个美女-电影写真-16:9
```
风格参数和比例参数没抓也没写，支持什么风格和比例自行去问小白推理生图查看

### 识图
使用 "小白识图 这个是什么" 上传图片识别：
```
小白识图 这个是什么
```
### 首次使用
首次使用时会自动提示登录：
1. 输入手机号码
2. 输入收到的验证码
3. 登录成功后即可开始使用

## 配置说明

配置文件 `config.json` 会自动生成，包含以下字段：
- phone: 登录手机号
- token: 登录令牌
- device_id: 设备ID
- conversation_id: 会话ID
- user_id: 用户ID
- web_id: 网页ID

## 注意事项

1. 请确保网络环境良好
2. 验证码有效期较短，请及时输入
3. 如遇登录失败，可以重新触发登录流程
