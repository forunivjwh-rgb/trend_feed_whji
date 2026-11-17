"""Agent Reach 연결: 가짜 도구로 확인한다(진짜 설치·인터넷 없음)."""

import os
import unittest
from unittest import mock

from trendfeed import agentreach, config, deepread

SETTINGS = config.load()
CFG = {**SETTINGS["agent_reach"], "enabled": True}
DR = {**SETTINGS["deepread"], "max_chars": 8000, "comments": 20, "github_issues": 1}


def ok(text, **extra):
    return {"ok": True, "items": [{"text": text, **extra}], "error": None}


def err(code):
    return {"ok": False, "items": None, "error": {"code": code, "message": "x"}}


class Runner:
    """Agent Reach 흉내. 받은 인자를 기억하고 채널마다 정해 둔 답을 준다."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, args):
        self.calls.append(args)
        answer = self.answers[args[0]]
        return answer(args) if callable(answer) else answer


class ReachTest(unittest.TestCase):
    def test_blocked_platform_stops_that_channel_for_the_day(self):
        runner = Runner({"youtube": err("PLATFORM_BLOCKED"), "github": ok("readme")})
        reach = agentreach.Reach(CFG, runner=runner)
        with self.assertRaises(agentreach.Stopped):
            reach.call("youtube", "subtitle", "u")
        with self.assertRaises(agentreach.Stopped):  # 두 번째는 부르지도 않는다
            reach.call("youtube", "subtitle", "u2")
        self.assertEqual(len(runner.calls), 1)
        self.assertFalse(reach.allowed("youtube"))
        self.assertEqual(reach.call("github", "read", "a/b")[0]["text"], "readme")  # 다른 채널은 그대로
        self.assertIn("멈춤: 유튜브: 로봇 아님 확인을 요구함", reach.summary())
        self.assertIn("GitHub 1회", reach.summary())

    def test_rate_limit_also_stops_but_one_missing_subtitle_does_not(self):
        reach = agentreach.Reach(CFG, runner=Runner({"youtube": err("NOT_FOUND"), "github": err("RATE_LIMITED")}))
        with self.assertRaises(agentreach.Failed):
            reach.call("youtube", "subtitle", "u")
        self.assertTrue(reach.allowed("youtube"))
        with self.assertRaises(agentreach.Stopped):
            reach.call("github", "read", "a/b")
        self.assertFalse(reach.allowed("github"))

    def test_login_channels_are_never_called(self):
        runner = Runner({})
        reach = agentreach.Reach(CFG, runner=runner)
        for channel in ("instagram", "reddit", "twitter", "web"):
            self.assertFalse(reach.allowed(channel))
            with self.assertRaises(agentreach.Unavailable):
                reach.call(channel, "read", "x")
        self.assertEqual(runner.calls, [])

    def test_disabled_or_not_installed_is_unavailable(self):
        with self.assertRaises(agentreach.Unavailable):
            agentreach.Reach({**CFG, "enabled": False})
        with mock.patch.object(agentreach, "binary", lambda cfg: None), self.assertRaises(agentreach.Unavailable):
            agentreach.Reach(CFG)

    def test_tool_gets_no_keys_in_its_environment(self):
        fake = {"PATH": "/usr/bin", "ANTHROPIC_API_KEY": "k1", "YOUTUBE_API_KEY": "k2", "GITHUB_TOKEN": "k3",
                "GH_TOKEN": "k4", "HTTPS_PROXY": "http://proxy:1"}
        with mock.patch.dict(os.environ, fake, clear=True), \
                mock.patch.object(agentreach, "binary", lambda cfg: agentreach.config.ROOT / "x" / "agent-reach"):
            env = agentreach._env(CFG)
        self.assertFalse({"ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"} & set(env))
        self.assertEqual(env["HTTPS_PROXY"], "http://proxy:1")
        self.assertTrue(env["HOME"].endswith("state"))

    def test_install_spec_is_the_pinned_fork_commit_not_pypi(self):
        self.assertEqual(agentreach.spec(CFG), f"agent-reach @ git+{CFG['repo']}@{CFG['commit']}")
        self.assertRegex(CFG["commit"], r"^[0-9a-f]{40}$")
        self.assertNotIn("web", CFG["channels"])  # 바깥 서비스로 주소를 보내는 채널은 사용자가 정하기 전까지 끔


class ReadersWithReachTest(unittest.TestCase):
    def test_youtube_reads_subtitles_with_agent_reach_then_description_and_comments(self):
        from tests.test_youtube import with_key

        class Fetch:
            def get_json(self, url, headers=None):
                if "/commentThreads" in url:
                    return {"items": [{"snippet": {"topLevelComment": {"snippet": {"textOriginal": "댓글"}}}}]}
                return {"items": [{"id": "-vid", "snippet": {"title": "t", "description": "설명"}}]}

        runner = Runner({"youtube": ok("안녕하세요\n여러분")})
        reach = agentreach.Reach(CFG, runner=runner)
        with with_key():
            material, scope = deepread._read_youtube({"source": "youtube", "external_id": "-vid"}, DR,
                                                     SETTINGS["sources"], Fetch(), reach)
        self.assertTrue(material.startswith("[자막]\n안녕하세요 여러분"))
        self.assertIn("[설명란]\n설명", material)
        self.assertEqual(scope, "자막 9자(Agent Reach) · 설명란 2자 · 댓글 상위 1")
        # 영상 번호가 "-" 로 시작해도 옵션으로 오해받지 않게 주소로 넘긴다
        self.assertEqual(runner.calls[0][:3], ["youtube", "subtitle", "https://www.youtube.com/watch?v=-vid"])

    def test_youtube_without_api_key_still_reads_subtitles(self):
        from tests.test_youtube import with_key

        reach = agentreach.Reach(CFG, runner=Runner({"youtube": ok("자막 내용")}))
        with with_key(None):
            material, scope = deepread._read_youtube({"source": "youtube", "external_id": "v"}, DR,
                                                     SETTINGS["sources"], None, reach)
        self.assertEqual((material, scope), ("[자막]\n자막 내용", "자막 5자(Agent Reach)"))

    def test_github_reads_readme_and_top_issue_and_falls_back_when_blocked(self):
        issues = [{"number": 7, "title": "PR", "comments": 50, "pull_request": {}, "html_url": "u7"},
                  {"number": 3, "title": "버그", "comments": 12, "body": "본문", "html_url": "https://github.com/a/b/issues/3"}]

        class Fetch:
            def __init__(self):
                self.urls = []

            def get_json(self, url, headers=None):
                self.urls.append(url)
                return issues

            def get_text(self, url, headers=None):
                self.urls.append(url)
                return "직접 읽은 README"

        e = {"source": "github_trending", "external_id": "a/b"}
        runner = Runner({"github": lambda args: ok("README 본문" if args[2] == "a/b" else "이슈와 댓글")})
        with mock.patch.object(config, "secret", lambda name: None):
            material, scope = deepread._read_github(e, DR, SETTINGS["sources"], Fetch(),
                                                    agentreach.Reach(CFG, runner=runner))
            self.assertIn("[README]\nREADME 본문", material)
            self.assertIn("[이슈]\n#3 버그\n이슈와 댓글", material)
            self.assertEqual(scope, "README 9자(Agent Reach) · 이슈 1(댓글 12)(Agent Reach)")
            self.assertEqual(runner.calls[1][2], "https://github.com/a/b/issues/3")  # PR은 건너뛴다
            # GitHub가 횟수 제한으로 막으면 그날은 직접 읽는다
            blocked = agentreach.Reach(CFG, runner=Runner({"github": err("RATE_LIMITED")}))
            fetch = Fetch()
            material, scope = deepread._read_github(e, DR, SETTINGS["sources"], fetch, blocked)
        self.assertIn("[README]\n직접 읽은 README", material)
        self.assertIn("#3 버그\n본문", material)
        self.assertEqual(scope, "README 12자 · 이슈 1(댓글 12)")
        self.assertIn("https://raw.githubusercontent.com/a/b/HEAD/README.md", fetch.urls)

    def test_deepread_records_the_tool_line_for_the_feed(self):
        from tests.test_deepread import DAY, DeepreadTest, FakeClient

        t = DeepreadTest("test_raw_text_is_never_stored")
        t.setUp()
        try:
            reach = agentreach.Reach(CFG, runner=Runner({}))
            deepread.run(t.conn, DAY, {**SETTINGS, "deepread": {**SETTINGS["deepread"], "pause_sec": 0}},
                         __import__("tests.test_deepread", fromlist=["Fetch"]).Fetch(), client=FakeClient(),
                         say=lambda s: None, reach=reach)
            row = t.conn.execute("SELECT deepread_tool FROM daily_runs WHERE date = ?", (DAY,)).fetchone()
            self.assertEqual(row[0], f"Agent Reach({CFG['commit'][:7]}) 부른 적 없음")  # 위키는 직접 읽는다
        finally:
            for cleanup in reversed(t._cleanups):
                cleanup[0](*cleanup[1], **cleanup[2])


if __name__ == "__main__":
    unittest.main()
