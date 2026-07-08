# 项目记忆

## 技术栈
- Python 3.13 + uv 管理依赖，FastAPI 后端，Next.js 前端 (web/)
- 运行环境: `.venv/bin/python` (uv venv)，测试用 `python -m unittest`（pytest 未安装）
- 邮箱注册流程在 `services/register/openai_register.py`，邮箱 provider 在 `services/register/mail_provider.py`

## OpenAI 注册流程关键点
- Sentinel token 用 FNV-1a PoW（auth.openai.com），不是 SHA3-512（chatgpt.com 的 utils/pow.py）
- `create_account` 阶段必须同时带 `OpenAI-Sentinel-Token` 和 `OpenAI-Sentinel-SO-Token`
- SO token 来源在 Sentinel /req 返回的 `so` 字段，生成方式和 PoW 类似（seed/difficulty），也可能以 turnstile dx 形式出现
- turnstile dx 的 XOR 密钥用 requirements_token（gAAAAAC 前缀），不是 PoW 解（gAAAAAB 前缀）
- 注册流程必须包含 authorize/continue 步骤（邮箱提交），否则 create_account 会 registration_disallowed
- SO token observer 等待 5000ms
- 某些临时邮箱域名会被最终风控拒绝，需按 provider/domain 统计成功率并停用低成功率域名

## 文件位置
- Sentinel token 生成: `utils/sentinel.py`（含 `build_sentinel_tokens` 返回 sentinel+so token）
- Turnstile dx 解: `utils/turnstile.py`
- 注册主流程: `services/register/openai_register.py`
- 域名统计: `services/register/domain_stats.py`（存储在 `data/register_domain_stats.json`）
- 注册 API: `api/register.py`
