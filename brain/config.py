from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # ==========================================
    # 1. 环境依赖 & 沙盒路径
    # ==========================================
    api_token: str
    llm_api_key: str
    llm_base_url: str
    desktop_path: str

    # ==========================================
    # 2. AI 模型参数 (完全继承原有设定)
    # ==========================================
    llm_model_name: str = "gemini-3.1-flash-lite"
    llm_temperature: float = 0.3
    prompt_file_path: str = "core/prompt_templates.txt" # 路径更新
    agent_request_timeout: float = 80.0
    weather_api_url: str = "https://wttr.in/{city}?format=3"
    weather_timeout: float = 20.0

    # ==========================================
    # 3. RPA 物理引擎参数
    # ==========================================
    cmd_encodings: list[str] = ["gbk", "utf-8", "cp437"]
    cmd_max_output_length: int = 2000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()