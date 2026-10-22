"""Exercise only the synthesis block, never the model/DB/pipeline side effects."""
import ast
import inspect
import pytest
from behive.engine import orchestrator as orch
from behive.engine import fact_synth
from test_pipeline_failures import DB


def synthesis(mid, query, timings):
    if hasattr(orch, '_run_synthesis'):
        return orch._run_synthesis(mid, query, timings)
    # Baseline has no seam: compile the exact affected statements, unchanged.
    tree = ast.parse(inspect.getsource(orch._run_pipeline_phases))
    body = tree.body[0].body
    start = next(i for i,n in enumerate(body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id == '_fact_ok' for t in n.targets))
    end = next(i for i,n in enumerate(body[start:],start) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id == '_emit' and any(isinstance(a,ast.Constant) and a.value == 'completed' for a in n.value.args))
    block = ast.Module(body=body[start:end+1],type_ignores=[])
    exec(compile(block,'baseline-synthesis','exec'),orch.__dict__, {'mission_id':mid,'query':query,'timings':timings})


@pytest.fixture
def boundary(monkeypatch):
    db = DB()
    events = []
    monkeypatch.setattr(orch,'_connect_db',lambda **kw: db)
    monkeypatch.setattr(orch,'_emit',lambda mid,phase,event,**kw: events.append((phase,event,kw)))
    return db,events


def test_exhausted_synthesis_raises_and_never_emits_completed(monkeypatch,boundary):
    db,events = boundary
    monkeypatch.setattr(fact_synth,'persist_fact_synthesis',lambda mid: {'claims':0})
    def fail(*args,**kw): raise RuntimeError('secret-token=request-body')
    monkeypatch.setattr(orch,'run_phase',fail)
    with pytest.raises(RuntimeError,match='synthesis failed'):
        synthesis('m','topic',{})
    assert any(e == 'failed' for p,e,d in events)
    assert not any(e == 'completed' for p,e,d in events)
    assert 'secret-token' not in repr(events)


def test_exit_zero_without_provenance_never_emits_completed(monkeypatch,boundary):
    db,events = boundary
    db.claim(evidence=False)
    monkeypatch.setattr(fact_synth,'persist_fact_synthesis',lambda mid: {'claims':0})
    monkeypatch.setattr(orch,'run_phase',lambda *args,**kw: 0.1)
    synthesis('m','topic',{})
    assert not any(e == 'completed' for p,e,d in events)
    assert any(e == 'empty' for p,e,d in events)


def test_fact_recovery_with_product_emits_completed(monkeypatch,boundary):
    db,events = boundary
    for _ in range(3): db.claim()
    outcomes = iter([{'claims':0},{'claims':3}])
    monkeypatch.setattr(fact_synth,'persist_fact_synthesis',lambda mid: next(outcomes))
    def fail(*args,**kw): raise RuntimeError('request-body')
    monkeypatch.setattr(orch,'run_phase',fail)
    synthesis('m','topic',{})
    completed = next(d['data'] for p,e,d in events if e == 'completed')
    assert completed['synthesis_method'] == 'fact'
    assert completed['completion_basis'] == 'qualified_claims'
    assert 'inference_success' not in completed


def test_claim_count_without_actual_evidence_is_not_fact_product(monkeypatch,boundary):
    db,events = boundary
    monkeypatch.setattr(fact_synth,'persist_fact_synthesis',lambda mid: {'claims':3})
    synthesis('m','topic',{})
    assert not any(e == 'completed' for p,e,d in events)
