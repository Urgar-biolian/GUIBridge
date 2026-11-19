"""The independent verifier (PRD §5.4, docs/agent.md trust boundary): Git scope + acceptance exit codes.

These tests run against real throwaway repositories so the scope judgement is a real `git status`,
and they inject the runner for the acceptance commands so no toolchain is needed. The injected
runner records the argv it was handed and never executes it, which is how the never-a-shell rule is
pinned rather than asserted in prose.
"""

import sys
from pathlib import Path

import pytest
from execution.verifier import OUTPUT_TAIL, Verifier, _argv

# The `recorder` and `verifier` fixtures live in conftest.py: the handoff tests reuse the same runner
# double, and the recorder never executes an acceptance command, so no toolchain is needed.
COMMAND = ["npm", "test"]


def test_a_scope_clean_change_with_passing_tests_is_verified(scratch_repo, verifier, recorder):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    outcome = verifier.verify(scratch_repo.path, ["src/"], [COMMAND])
    assert outcome["status"] == "verified" and outcome["verified"] is True
    assert outcome["reasons"] == []
    assert outcome["changed_files"] == ["src/app.js"]
    assert outcome["head"] == scratch_repo.head() and outcome["since_rev"] is None
    assert recorder.executed == [COMMAND]


def test_claimed_done_without_any_change_proves_nothing(scratch_repo, verifier, recorder):
    recorder.outcomes = [(1, "", "no tests: the feature is missing\n")]
    outcome = verifier.verify(scratch_repo.path, ["src/"], [COMMAND])
    assert outcome["status"] == "failed" and outcome["verified"] is False
    assert any(reason.startswith("no_changes") for reason in outcome["reasons"])


def test_a_change_outside_the_allowed_paths_is_refused(scratch_repo, verifier):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    scratch_repo.write("README.md", "the executor also touched this\n")
    outcome = verifier.verify(scratch_repo.path, ["src/"], [COMMAND])
    assert outcome["status"] == "failed"
    assert outcome["out_of_scope"] == ["README.md"]
    assert any("README.md" in reason and reason.startswith("out_of_scope") for reason in outcome["reasons"])


def test_a_failing_acceptance_command_blocks_verified(scratch_repo, recorder, verifier):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    recorder.outcomes = [(1, "", "AssertionError: expected 2 to be 3\n")]
    outcome = verifier.verify(scratch_repo.path, ["src/"], [COMMAND])
    assert outcome["status"] == "failed" and outcome["verified"] is False
    assert outcome["tests"] == [
        {"command": COMMAND, "returncode": 1, "passed": False, "stdout_tail": "",
         "stderr_tail": "AssertionError: expected 2 to be 3\n"}]
    assert any(reason.startswith("test_failed") for reason in outcome["reasons"])


def test_every_configured_command_has_to_pass(scratch_repo, recorder, verifier):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    recorder.outcomes = [(0, "unit ok\n", ""), (1, "", "lint reported problems\n")]
    outcome = verifier.verify(scratch_repo.path, ["src/"], [COMMAND, ["npm", "run", "lint"]])
    assert outcome["status"] == "failed"
    assert [test["passed"] for test in outcome["tests"]] == [True, False]
    assert outcome["evidence"]["test_exit_codes"] == [0, 1]
    assert len([reason for reason in outcome["reasons"] if reason.startswith("test_failed")]) == 1


def test_nothing_is_verified_without_an_acceptance_command(scratch_repo, verifier, recorder):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    outcome = verifier.verify(scratch_repo.path, ["src/"], [])
    assert outcome["status"] == "failed"
    assert any(reason.startswith("no_acceptance_tests") for reason in outcome["reasons"])
    assert recorder.executed == []


def test_a_directory_pattern_covers_the_subtree_but_a_file_pattern_does_not(scratch_repo, verifier):
    scratch_repo.write("src/nested/deep.js", "export const deep = 1;\n")
    assert verifier.verify(scratch_repo.path, ["src/"], [COMMAND])["status"] == "verified"

    scratch_repo.commit("deep change")
    scratch_repo.write("src/nested/deep.js", "export const deep = 2;\n")
    outcome = verifier.verify(scratch_repo.path, ["src/app.js"], [COMMAND])
    assert outcome["out_of_scope"] == ["src/nested/deep.js"]


def test_changes_the_executor_committed_are_counted_and_baselined(scratch_repo, verifier):
    """Agent mode commits its own work, so `since_rev` is what makes an empty tree mean anything."""
    head = scratch_repo.head()
    scratch_repo.write("src/app.js", "export const value = 3;\n").commit("agent: implement the task")
    outcome = verifier.verify(scratch_repo.path, ["src/"], [COMMAND], since_rev=head)
    assert outcome["status"] == "verified"
    assert outcome["committed_since"] == ["src/app.js"]
    assert outcome["changes"]["modified"] == []


def test_committed_changes_outside_the_scope_are_still_caught(scratch_repo, verifier):
    head = scratch_repo.head()
    scratch_repo.write("src/app.js", "export const value = 3;\n").commit("agent: the requested change")
    scratch_repo.write("docs/secret.md", "not in the task package\n").commit("agent: out of scope")
    outcome = verifier.verify(scratch_repo.path, ["README.md"], [COMMAND], since_rev=head)
    assert outcome["status"] == "failed"
    assert sorted(outcome["out_of_scope"]) == ["docs/secret.md", "src/app.js"]


def test_untracked_and_deleted_and_renamed_files_land_in_buckets(scratch_repo, verifier):
    scratch_repo.write("notes.txt", "written but never committed\n")
    scratch_repo.remove("README.md")
    scratch_repo.run("mv", "src/app.js", "src/renamed.js")
    outcome = verifier.verify(scratch_repo.path, ["src/", "notes.txt", "README.md"], [COMMAND])
    buckets = outcome["changes"]
    assert buckets["untracked"] == ["notes.txt"]
    assert buckets["deleted"] == ["README.md"]
    assert sorted(buckets["renamed"] + buckets["modified"]) == ["src/renamed.js"]
    assert outcome["status"] == "verified"


def test_the_diff_and_changed_paths_are_carried_as_evidence(scratch_repo, verifier):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    evidence = verifier.verify(scratch_repo.path, ["src/"], [COMMAND])["evidence"]
    assert evidence["porcelain_changed"] == ["src/app.js"]
    assert "src/app.js" in evidence["diff_stat"]
    assert evidence["test_exit_codes"] == [0]


def test_acceptance_commands_are_handed_over_as_argv_never_to_a_shell(scratch_repo, verifier, recorder):
    """A sentence from the chat panel has no shell meaning here: it stays inert argv elements."""
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    payload = "rm -rf src && touch PWNED ; echo $(whoami)"
    verifier.verify(scratch_repo.path, ["src/"], [payload])
    assert recorder.executed[0] == ["rm", "-rf", "src", "&&", "touch", "PWNED", ";", "echo", "$(whoami)"]
    assert (scratch_repo.path / "PWNED").exists() is False
    assert (scratch_repo.path / "src" / "app.js").exists() is True


def test_a_windows_path_keeps_its_backslashes():
    assert _argv(r"C:\tools\node.exe --test tests/*.test.mjs") == [r"C:\tools\node.exe", "--test",
                                                                  "tests/*.test.mjs"]


@pytest.mark.parametrize("command", ["", '""', "  ", [" "], ["npm", ""]])
def test_an_empty_command_is_refused_instead_of_run(scratch_repo, verifier, recorder, command):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    outcome = verifier.verify(scratch_repo.path, ["src/"], [command])
    assert outcome["status"] == "failed"
    assert any(reason.startswith("test_error") for reason in outcome["reasons"])
    assert recorder.executed == []


def test_a_missing_executable_is_a_reason_not_a_crash(scratch_repo):
    """The real runner, because a tool that is not installed must not abort the whole verification."""
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    outcome = Verifier().verify(scratch_repo.path, ["src/"], [["definitely-not-a-real-binary"]])
    assert outcome["status"] == "failed"
    assert outcome["tests"][0]["returncode"] is None
    assert "could not run" in outcome["tests"][0]["error"]
    assert any(reason.startswith("test_error") for reason in outcome["reasons"])


def test_a_failing_test_reports_the_tail_of_the_output(scratch_repo, recorder, verifier):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    recorder.outcomes = [(1, "x" * (OUTPUT_TAIL + 500), "y" * (OUTPUT_TAIL + 500))]
    outcome = verifier.verify(scratch_repo.path, ["src/"], [COMMAND])
    assert len(outcome["tests"][0]["stdout_tail"]) == OUTPUT_TAIL
    assert outcome["tests"][0]["stderr_tail"].endswith("yyyy")


def test_a_repository_that_is_not_a_repo_fails_loudly(verifier, tmp_path):
    with pytest.raises(RuntimeError, match="git status failed"):
        verifier.verify(tmp_path, ["src/"], [COMMAND])


def test_verifying_a_path_object_is_allowed(scratch_repo, verifier):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    outcome = verifier.verify(Path(scratch_repo.path), ["src/"], [COMMAND])
    assert outcome["status"] == "verified"
    assert isinstance(outcome["repo_path"], str)


# The perception lane and the MCP `verify_task` tool build one verifier per task and then call it
# with no arguments, and a store-backed verifier is the only writer of the `verified` task state.
# Both are merged-surface promises, so they are pinned against the same fixtures as the checks
# above (no node, no real toolchain: the recorder answers `git` for real and the rest as argv).


def test_a_configured_verifier_answers_a_bare_call(scratch_repo, recorder):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    configured = Verifier(scratch_repo.path, ["src/"], [COMMAND], runner=recorder)
    outcome = configured.verify()
    assert outcome["status"] == "verified" and outcome["changed_files"] == ["src/app.js"]
    assert outcome["allow_files"] == ["src/"] and recorder.executed == [COMMAND]


def test_the_verdict_carries_one_word_for_a_panel(scratch_repo, recorder):
    configured = Verifier(scratch_repo.path, ["src/"], [COMMAND], runner=recorder)
    assert configured.verify()["reason"] == "no_change"

    scratch_repo.write("README.md", "the executor also touched this\n")
    assert configured.verify()["reason"] == "out_of_scope_change"

    scratch_repo.commit("the out-of-scope edit is history now")
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    recorder.outcomes = [(1, "", "1 failing\n")]
    assert configured.verify()["reason"] == "tests_failed"


def test_an_out_of_scope_change_outranks_a_red_test(scratch_repo, recorder):
    """A reader fixes the scope violation first, so the single word names that one."""
    scratch_repo.write("README.md", "out of scope\n")
    recorder.outcomes = [(1, "", "1 failing\n")]
    configured = Verifier(scratch_repo.path, ["src/"], [COMMAND], runner=recorder)
    assert configured.verify()["reason"] == "out_of_scope_change"


def test_an_unrunnable_tool_is_a_result_with_a_code(scratch_repo, recorder):
    """The A-lane convention survives: a command that never started is not a passing run."""
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    recorder.outcomes = [OSError(2, "The system cannot find the path specified")]
    outcome = Verifier(scratch_repo.path, ["src/"], [COMMAND], runner=recorder).verify()
    assert outcome["status"] == "failed"
    assert outcome["tests"][0]["returncode"] is None
    assert "could not run" in outcome["tests"][0]["error"]
    assert outcome["test_exit"] == 127


def test_a_timed_out_command_fails_instead_of_hanging(scratch_repo):
    """The real runner, because only a real timeout proves the verifier does not wait forever."""
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    outcome = Verifier(scratch_repo.path, ["src/"], [sleeper], timeout=1).verify()
    assert outcome["status"] == "failed"
    assert outcome["tests"][0]["returncode"] == 124
    assert "timed out" in outcome["tests"][0]["stderr_tail"]


def test_a_claim_from_the_panel_never_stands_in_for_a_test(scratch_repo, recorder):
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    outcome = Verifier(scratch_repo.path, ["src/"], [], runner=recorder).verify(
        claimed_reply="已完成，npm test 全绿")
    assert outcome["status"] == "failed"
    assert outcome["claimed_reply_untrusted"] == "已完成，npm test 全绿"
    assert any(reason.startswith("no_acceptance_tests") for reason in outcome["reasons"])
    assert recorder.executed == []


def test_a_verified_run_writes_the_task_state_as_the_verifier(scratch_repo, recorder, store):
    task = store.create_task("t-verify", "trae", str(scratch_repo.path), acceptance={"commands": [COMMAND]})
    scratch_repo.write("src/app.js", "export const value = 2;\n")
    configured = Verifier(scratch_repo.path, ["src/"], [COMMAND], store=store, task_id=task["task_id"],
                          runner=recorder)
    report = configured.verify()
    assert report["verified"] is True
    assert store.get_task(task["task_id"])["state"] == "verified"
    assert store.get_task(task["task_id"])["transitions"][-1]["state"] == "verified"
    events = store.events(kind="verifier_run")
    assert events[-1]["payload"]["changed_files"] == ["src/app.js"]
    assert report["evidence_id"] == events[-1]["event_id"]


def test_a_failed_run_leaves_the_task_short_of_verified(scratch_repo, recorder, store):
    task = store.create_task("t-fail", "trae", str(scratch_repo.path))
    recorder.outcomes = [(1, "", "AssertionError\n")]
    configured = Verifier(scratch_repo.path, ["src/"], [COMMAND], store=store, task_id=task["task_id"],
                          runner=recorder)
    assert configured.verify()["verified"] is False
    assert store.get_task(task["task_id"])["state"] == "failed"
