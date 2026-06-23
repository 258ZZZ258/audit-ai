# 编排 / 状态机 / 队列 devlog(pipeline/pipeline)

**职责**:`orchestrator.py`(单进程轮询 worker)· `states.py`(状态机 + 迁移表 + 错误码)· `stage_base.py`(StageContext/StageResult/QueueItem)· `queue.py`(统一队列 dispose)· `orchestration.py`(编排接缝)。

## 关键决策 / 踩坑
- **states(A3)**:13 态 demo 子集(无 REPARSE)+ 合法迁移表 + reprocess + 三态集分区 + 错误码(E1xx–E8xx,demo 专属 `-DEMO`)。
- **orchestrator(B1)**:**stage 注入式**(`Orchestrator(pg, ctx, stages: dict[state→stage])`),只轮询 `WORKER_ADVANCEABLE_STATES` 中**且已注册 stage** 的态 → 人工等待态结构上永不被轮询。stage 纯函数;orchestrator owns 迁移 + `pipeline_events`(经 `pg_io.transition`,内含 `can_transition` 守卫)+ 入队。
- **queue dispose(B6)**:5 处置(fix/degrade/reject/release/approve)各为**三写原子单元**(迁移+events / remediation_records / 关单)。两层校验:queue_type↔disposition 相容 + `can_transition`(非法 → ValueError 整事务回滚)。原子性靠 **`transition` session 注入**(`session=` 加入调用方事务)。
- **踩坑**:SQLAlchemy 无 relationship 不自动排 FK 插入序 → `flush()`(父先于子);ULID `[:8]` 截断=时间戳前缀,同毫秒相撞 → 用完整 ULID。

## B 模式驱动正确性 + 过渡态守卫(阶段 W / 升格)
B 模式下 ingest/dispose 重入会自动越过 META_REVIEW、需 s5 到终态;若用轻上下文(无 embedding/milvus)→ **永久搁浅 EMBEDDING 却返回成功(exit 0)**。修:① `_advance_one` 加**通用过渡态守卫**——干净停在 EMBEDDING/INDEXING 即报错(静默搁浅→响亮失败);② 重入路径用 `_drive_context`(B→worker);③ `_finalize_if_indexed` 抽出(凡能到 INDEXED 的驱动共用,补 orchestrator 不调的 finalize)。CLI 可靠性契约见 `CLAUDE.md`。

## 编排接缝(升格 Step 3b)
`orchestration.py`:`WorkflowEngine` Protocol(`step`/`run_until_idle`);`StateMachineWorkflow = Orchestrator`(demo 默认,结构上满足 Protocol);`TemporalWorkflow` stub(触发=信创内网 Temporal 可部署性验证通过);`make_workflow_engine` 读 `PIPELINE_WORKFLOW_BACKEND`(默认 state_machine)。cli 两处构造改走工厂。

> 时间轴:`docs/devlog.md` 阶段 A(A3)、阶段 B(B1/B6 + B 段审查)、阶段 W、升格 Step 3b。
