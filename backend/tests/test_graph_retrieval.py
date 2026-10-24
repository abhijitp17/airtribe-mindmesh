"""Graph-aware retrieval: alias expansion and defining passages, without weakening the coverage gate."""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{tmp}/t.db", "STORAGE_DIR": tmp, "AI_PROVIDER": "mock"})

from app.core.graph_retrieval import GraphHints, defining_chunks, expand_query, mentioned, promote  # noqa: E402
from app.services.knowledge_graph import canonical_key as k  # noqa: E402
from app.services.learning import ChunkData, retrieve  # noqa: E402

TEXTS = [
    ("c1", "Flow basics", "A production line moves jobs from station to station. Each station has a processing rate."),
    ("c2", "Work in process", "Work in process is the inventory of jobs that have started but not finished. "
                              "Keeping work in process low shortens how long each job waits."),
    ("c3", "Cycle time", "Cycle time is the time a job spends in the line from release to completion."),
    ("c4", "Throughput", "Throughput is the rate at which finished jobs leave the line."),
    ("c5", "Variability", "Variability in arrivals and processing makes queues longer and less predictable."),
    ("c6", "Capacity", "Capacity is the most a station can produce per hour when it never starves."),
    ("c7", "Batching", "Batching groups jobs together, which can raise waiting at downstream stations."),
]
CHUNKS = [ChunkData(cid, f"{sec}. {text}", i + 1, i + 1, sec, "d1") for i, (cid, sec, text) in enumerate(TEXTS)]
HINTS = GraphHints(
    names={k("WIP"): ["Work in process", "WIP"], k("Work in process"): ["Work in process", "WIP"]},
    defining_chunks={k("Work in process"): ["c2"]},
    kept={k("WIP"): k("Work in process"), k("Work in process"): k("Work in process")},
)


def test_mentions_are_whole_words_and_longest_first():
    assert mentioned("Why does WIP matter?", HINTS) == [k("Work in process")]
    assert mentioned("How do I wipe the data?", HINTS) == []
    assert mentioned("work in process and WIP", HINTS) == [k("Work in process")]


def test_expansion_adds_other_names_only():
    assert expand_query("What is WIP?", HINTS) == "What is WIP? (Work in process)"
    assert expand_query("What is work in process?", HINTS) == "What is work in process? (WIP)"
    assert expand_query("What is throughput?", HINTS) == "What is throughput?"
    assert expand_query("What is WIP?", None) == "What is WIP?"


def test_promote_only_moves_candidates_in():
    assert promote(["a", "b", "c"], ["a", "b", "c", "x"], ["x"], 3) == ["a", "b", "x"]
    assert promote(["a", "b"], ["a", "b"], ["x"], 3) == ["a", "b"], "not a candidate: not added"
    assert promote(["a", "x"], ["a", "x"], ["x"], 3) == ["a", "x"]
    assert defining_chunks("Explain WIP", HINTS) == ["c2"]


def test_an_acronym_question_finds_the_passage_only_with_the_graph():
    q = "What is WIP?"
    without = [s.chunk_id for s in retrieve(CHUNKS, q)]
    with_graph = [s.chunk_id for s in retrieve(CHUNKS, q, hints=HINTS)]
    assert "c2" not in without[:1]
    assert with_graph[0] == "c2"


def test_no_hints_changes_nothing_and_off_topic_is_still_not_found():
    for q in ("How does throughput relate to cycle time?", "What is batching?"):
        assert [s.chunk_id for s in retrieve(CHUNKS, q)] == [s.chunk_id for s in retrieve(CHUNKS, q, hints=GraphHints())]
    assert retrieve(CHUNKS, "What is the capital of Peru?", hints=HINTS) == []
