-- Task 3: task_transition() — the sole writer of tasks.state.
--
-- Why this function is load-bearing rather than belt-and-braces. The vocabulary trigger
-- shipped by 0001 (`reject_undocumented_state`) only checks that the VALUE landing in
-- tasks.state appears somewhere in state_edges; it says nothing about whether the EDGE
-- is declared. Review live-proved that CREATED -> COMPLETED sails through it, and ruling
-- P-6 legitimately grants authority_app UPDATE on tasks so a fencing token can be bumped.
-- The state_edges EXISTS guard below is therefore the only thing between this schema and
-- an illegal jump. Do not weaken it, and do not reorder the guards: each guard owns one
-- distinct reason code, Tasks 4/5/6/7/10 assert those exact codes, and the order recorded
-- here is found -> token -> edge -> evidence -> slot.
--
-- The tuple lock taken on the tasks row is what makes Task 5's 20-writer race resolve to
-- exactly one winner: the losers serialise behind it, re-read the winning state, and then
-- fall out on the edge guard — one OK row and nineteen ILLEGAL_EDGE rows, as the ledger's
-- T5 arithmetic expects.
--
-- Literal-text contract with Task 11: the harness anchors on four exact substrings of
-- this file and reports SKIP-INVALID for any anchor whose hit count is not 1. Four lines
-- below are those anchors (the tuple lock clause, the token comparison, the mock-adapter
-- test, and the outbox insert column list). None of them may be duplicated — not in code
-- and not in a comment — or Task 11's verdict for the whole suite stops meaning anything.
--
-- DEFECT FOUND IN THE BRIEF, AND IT IS THE WORST KIND. `RETURN QUERY` does not exit a
-- PL/pgSQL function — the docs are explicit that only a plain `RETURN` ends execution —
-- so every guard in the brief's body kept running after it "returned" its rejection and
-- fell through to the UPDATE, the audit insert and the outbox insert. Live-measured on
-- the brief's own SQL: one refused CREATED->COMPLETED emitted TWO rows, set the state to
-- COMPLETED, wrote the ILLEGAL_EDGE reject row AND an OK audit row, and queued a
-- `task.COMPLETED` outbox event. The reason code still read correctly, because the
-- wrapper's fetchrow takes the first row — so every reason-code assertion passes while the
-- database is corrupted underneath it, which is precisely the "silence looks healthy"
-- failure class spec §17.12 exists to catch. The rejection branches below are therefore
-- each terminated with a plain `return;`, and tests/test_transitions.py pins both halves:
-- the refused call emits exactly one row, and it emits no event and no state change.
--
-- SECURITY: this function is NOT a definer-side function, deliberately — Plan 3 owns that
-- change, and it must arrive together with a pinned search_path, because a definer function
-- without one is a privilege-escalation surface. Tests run as the cluster superuser today,
-- so such a boundary could not even be proven here.

-- Rejections are audited through the same helper so no guard can "forget" its trail.
-- after_state is NULL on purpose: a rejected transition has no resulting state, and an
-- empty string would be a lie of a different shape.
create or replace function audit_reject(
  p_actor text, p_action text, p_target text, p_before text, p_reason text, p_token bigint
) returns void as $$
  insert into audit_events(actor,action,target,before_state,after_state,fencing_token,outcome)
  values (p_actor,p_action,p_target,p_before,null,p_token,p_reason);
$$ language sql;

create or replace function task_transition(
  p_task_id bigint, p_to_state text, p_token bigint, p_evidence jsonb, p_actor text
) returns table(ok boolean, reason text, new_state text) as $$
declare
  v_state text; v_token bigint; v_slot text; v_found boolean;
begin
  select t.state, t.fencing_token, t.assigned_slot_id into v_state, v_token, v_slot
    from tasks t where t.id = p_task_id
      for update;
  v_found := found;
  if not v_found then
    -- Deviation from the brief, and it is a real one. The brief returned NOT_FOUND
    -- silently, which is the failure mode this whole plan exists to eliminate: a
    -- transition attempt against a task id that does not exist would leave NO trace, so
    -- "nothing was attempted" and "an attempt was refused" read identically. Spec §6 says
    -- a refusal is a rejection, not a no-op, and this task's contract says every
    -- rejection is audited. before_state stays NULL because there is no row to read —
    -- the target and the presented token are what the trail has to carry.
    perform audit_reject(p_actor,'transition',p_task_id::text,null::text,'NOT_FOUND',p_token);
    return query select false, 'NOT_FOUND', null::text;
    return;
  end if;

  -- Fail closed on a presented token that is absent. SQL three-valued logic means the
  -- comparison below evaluates to NULL — NOT true — when p_token is NULL, so the guard
  -- falls OPEN for a caller that presents no token at all, and the write path runs. That
  -- is not hypothetical: measured against the brief's body, a NULL-token CREATED->PLANNED
  -- request passed the fence, updated the state, inserted its OK audit row, and was only
  -- stopped two statements later by the unrelated NOT NULL constraint on
  -- outbox_events.dedupe_key, surfacing as NotNullViolationError instead of a reason code.
  -- A fence that depends on somebody else's column constraint is not a fence, and Task 10
  -- reaches this function with an HTTP body somebody shapes. The anchor line after this
  -- branch must keep its exact text for Task 11, so the NULL case gets its own branch
  -- rather than a rewrite of the comparison — same BAD_TOKEN reason, audited with the NULL
  -- token the caller actually presented.
  if p_token is null then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,'BAD_TOKEN',null::bigint);
    return query select false, 'BAD_TOKEN', v_state;
    return;
  end if;

  -- Ruling T3-A: the mirror of the branch above, on the STORED side. Same three-valued
  -- logic, same fall-open shape — the comparison below is NULL, not true, when v_token
  -- itself is NULL, so the guard is skipped and a transition proceeds as if authorized
  -- against a row with no token to check. Review measured it live by running this
  -- function's body with v_token bound to NULL: reason=OK, the state advanced, an OK audit
  -- row was written and an outbox event queued.
  --
  -- Unreachable today, and that is exactly the problem. 0001 declares the stored column
  -- `bigint not null default 0`, so no INSERT can put a NULL in it and nothing on the write
  -- path can produce one — which means this fence is currently held shut by a column
  -- constraint rather than by the function's own logic. Constraints are editable by the next
  -- migration; the fence is not allowed to be one `alter table` away from falling open
  -- silently. The branch costs one comparison and makes the guarantee local.
  --
  -- Pinned twice in tests/test_transitions.py because the two halves fail differently:
  -- test_a_null_stored_token_fails_closed drives this branch (a probe built from this
  -- function's own stored source with v_token forced NULL, inside a rolled-back
  -- transaction), and test_the_stored_token_column_is_declared_not_null turns red the
  -- moment the constraint is relaxed, so the hole cannot reopen quietly.
  -- The anchor line below keeps its exact text and stays the only token comparison.
  if v_token is null then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,'BAD_TOKEN',p_token);
    return query select false, 'BAD_TOKEN', v_state;
    return;
  end if;

  if v_token <> p_token then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,'BAD_TOKEN',p_token);
    return query select false, 'BAD_TOKEN', v_state;
    return;
  end if;

  if not exists (select 1 from state_edges e
                  where e.from_state = v_state and e.to_state = p_to_state) then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,'ILLEGAL_EDGE',p_token);
    return query select false, 'ILLEGAL_EDGE', v_state;
    return;
  end if;

  if (select e.requires_evidence from state_edges e
       where e.from_state = v_state and e.to_state = p_to_state)
     and p_evidence is null then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,
                         'EVIDENCE_REQUIRED',p_token);
    return query select false, 'EVIDENCE_REQUIRED', v_state;
    return;
  end if;

  if p_to_state = 'QUEUED' and not exists (
       select 1 from worker_slots s
        where s.id = v_slot and s.verified_at is not null and s.adapter <> 'mock') then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,
                         'SLOT_NOT_VERIFIED',p_token);
    return query select false, 'SLOT_NOT_VERIFIED', v_state;
    return;
  end if;

  update tasks set state = p_to_state, updated_at = now(),
                   completed_at = case when p_to_state in ('COMPLETED','FAILED',
                       'CANCELLED','QUARANTINED') then now() else completed_at end
    where id = p_task_id;

  insert into audit_events(actor,action,target,before_state,after_state,fencing_token,
                           redacted_payload,outcome)
    values (p_actor,'transition',p_task_id::text,v_state,p_to_state,p_token,
            redact(coalesce(p_evidence,'{}'::jsonb)),'OK');

  insert into outbox_events(prompt_id,task_id,event_type,payload,dedupe_key)
    select t.prompt_id, p_task_id, 'task.'||p_to_state,
           jsonb_build_object('from',v_state,'to',p_to_state,'token',p_token),
           p_task_id||':'||p_to_state||':'||p_token
      from tasks t where t.id = p_task_id;

  return query select true, 'OK', p_to_state;
  -- Every `return query` in this function is followed by a plain `return;`, including the
  -- success path, so the invariant "one call emits exactly one row" is structural rather
  -- than something a later edit has to remember.
  return;
end $$ language plpgsql;
