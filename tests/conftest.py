import pytest

from gtm_core.agents import Context, discover
from gtm_core.config import Settings
from gtm_core.connectors.base import NullCRM
from gtm_core.connectors.slack import Slack
from gtm_core.store import Store


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.database_url = "sqlite:///:memory:"
    s.slack_webhook_url = s.slack_bot_token = None
    s.anthropic_api_key = s.openai_api_key = None
    s.offline = True
    s.license_path = tmp_path / "license.json"
    return s


@pytest.fixture
def manifests():
    return discover("agents")


@pytest.fixture
def ctx_for(settings, manifests):
    def make(agent_id):
        slack = Slack(settings)
        slack.post = lambda text, **kw: slack.sent.append({"text": text}) or {"ok": True}
        from gtm_core.connectors.sequencer import Sequencer
        return Context.build(settings, manifests[agent_id], store=Store("sqlite:///:memory:"), crm=NullCRM(), slack=slack,
                             sequencer=Sequencer(), dialer=__import__('gtm_core.connectors.dialer', fromlist=['Dialer']).Dialer())
    return make
