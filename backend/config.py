from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    ai_provider: str = 'azure'
    azure_openai_endpoint: str = ''
    azure_openai_api_key: str = ''
    azure_openai_deployment: str = ''
    azure_openai_api_version: str = '2024-10-21'
    openai_api_key: str = ''
    openai_base_url: str = 'https://api.openai.com/v1'
    openai_model: str = 'gpt-4.1-mini'
    reasoning_effort: str | None = None
    agent_timezone: str = 'Europe/Paris'
    mcp_command: str = 'npx'
    mcp_args: list[str] = ['-y', 'screenpipe-mcp@latest']
    mcp_timeout_seconds: float = Field(60, gt=0)
    request_timeout_seconds: float = Field(240, gt=0)
    max_agent_rounds: int = Field(12, ge=2, le=30)
    max_tool_result_chars: int = Field(24000, ge=1000)
    task_ttl_seconds: int = Field(3600, gt=0)
    max_stored_tasks: int = Field(200, gt=0)
    data_dir: str = '.data'
    max_execution_rounds: int = Field(60, ge=3, le=120)
    execution_timeout_seconds: float = Field(1800, gt=0)
    desktop_timeout_seconds: float = Field(20, gt=0)
    agent_overlay: bool = True  # AGENT_OVERLAY=false disables all overlay rendering
    agent_overlay_mascot: bool = True
    agent_overlay_mascot_path: str = 'assets/melonman_working'
    agent_overlay_mascot_size: int = Field(64, ge=32, le=256)
    agent_overlay_mascot_fps: float = Field(4, ge=1, le=30)
    discovery_enabled: bool = True
    nightshift_unfinished_pass: bool = True
    nightshift_demo: bool = True  # fill Night shift with clearly marked fake examples until real proposals exist
    nightshift_horizon_hours: int = Field(24, ge=2, le=72)
    nightshift_min_support: int = Field(2, ge=2, le=10)
    nightshift_min_probability: float = Field(0.6, ge=0.3, le=1)
    nightshift_poll_seconds: float = Field(30, gt=0)
    nightshift_startup_delay_seconds: float = Field(20, ge=0)
    sync_startup_delay_seconds: float = Field(2, ge=0)
    sync_initial_lookback_days: int = Field(1, ge=1, le=31)
    discovery_interval_minutes: int = Field(30, ge=5)
    discovery_startup_delay_seconds: float = Field(30, ge=0)
    discovery_lookback_days: int = Field(7, ge=1, le=31)
    discovery_chunk_hours: int = Field(24, ge=1, le=168)
    discovery_overlap_minutes: int = Field(5, ge=0, le=30)
    discovery_settle_seconds: int = Field(60, ge=0)
    discovery_medium_confidence: float = Field(0.65, ge=0, le=0.85)
    discovery_high_confidence: float = Field(0.85, ge=0.85, le=1)
