import pytest
from aegis.core.config import SystemConfig
from aegis.system2.client import OllamaGenerator


def test_airgap_client_and_config():
    # 1. Construct httpx client the Ollama class uses and assert trust_env is False
    gen = OllamaGenerator()
    assert gen.client.trust_env is False

    # 2. Assert the base URL host is loopback; passing http://example.com raises ValueError
    bad_config = SystemConfig(ollama_base_url="http://example.com:11434")
    with pytest.raises(ValueError) as excinfo:
        OllamaGenerator(config=bad_config)
    assert "Air-gap violation" in str(excinfo.value)

    # 3. Assert SystemConfig has no attribute typesafe_api_key and no allow_cloud_fallback
    import aegis.core.config as config_mod
    sys_cfg = config_mod.SystemConfig()
    assert not hasattr(sys_cfg, "typesafe_api_key")
    assert not hasattr(sys_cfg, "allow_cloud_fallback")
