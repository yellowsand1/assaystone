# Assaystone — 工作守则

> **先读 `GOALS.md`。** 它是唯一的宪法；本文件只是操作手册。
> 旧的“验收控制平面”方向草稿已废止，其中九类缺口保留在 `GOALS.md` §5。

## 我们在做什么

把一个 agent 的工作单元变成一张**证书**：通过、失败，或者必须由人来看 ——
连同证据、做出判定的检查、无法判定的检查，以及这次判定的成本。

不是 verifier 库，不是 eval 平台，不是 agent 框架。是**判定 + 证据**。

## 现在处于哪个阶段

**P0 — Spine。** 只做四件事：

1. certificate v1（哈希寻址、带 provenance、带版本）
2. `verify --certificate` 与 `certificate verify`
3. README 只讲一条路径：audit → check → certificate → CI
4. 冻结 lifecycle surface（`capability` / `gate` / `trail` / `receipt` /
   `waiver` / `plane` / `oracles` 中除 `transcript`、`verifier` 外的部分）

P0 结束前，不新增命令、不新增领域包、不新增检查、不新增 benchmark。

## 十条法则（违反任何一条，改动不合并）

1. 没有证据就没有判定；判定必须能指向可重新打开的证据。
2. 三值：pass / fail / escalate。不许猜。
3. 级联：确定性 → 测试 → 证据 → judge；judge 永远不能单独决定。
4. 独立性来自 provenance，不来自声明；agent 写的都是证词，降级。
5. contract 是产品；check 可替换。
6. 每个 check 必须有 clean case、defective case、声明的盲区、实测误报率。
7. 确定性层在普通 PR 上 < 1 秒；做不到就标明“仅 CI”。
8. 不造新品类：活在 pytest、CI、hook、PR 里。需要新 dashboard 就是失败。
9. 每个功能要么增加每次判定的证据，要么降低判定的成本；否则删除。
10. 一个外部用户胜过十个功能；没有外部用户的新 surface 不允许出现。

## 代码地图

```
kernel（可改）      model.py contract.py verifiers.py runner.py workspace.py
                    certificate.py episode.py audit.py reports.py
测量（可改）        failure_zoo.py goodhart.py mutate.py backtest.py
                    coverage.py compose.py reportcard.py stats.py
入口（可改）        cli.py pytest_plugin.py hooks/ adapters/ importers/
                    （产品面只有 audit / check / certificate / prove / hook）
冻结（不改）        plane.py oracles.py gate/trail/receipt/keys/waiver/
                    canary.py drill.py portfolio.py prepare.py nextstep.py
                    brief.py diff.py propose.py leaderboard.py
                    （全部位于 `assaystone lab`；旧名字保留为别名）
```

冻结区：可以修 bug、修测试、修文档；**不许加功能**。删除冻结区的代码是允许的，
且通常是对的 —— 先删，再问。

## 改动前

```bash
make test          # unittest, 全量
make pytest        # pytest, 全量
make lint
make demo-audit
```

新增行为必须同时有 clean case 和 defective case。永远不要为了让改动通过而削弱或删除测试。

## 绝对不要

- 以“再加一个 check / 领域包 / benchmark case”作为默认下一步。
- 给默认路径加网络、API key、LLM judge 或重依赖。
- 把 agent 的 transcript 当事实；它是对手写的。
- 在 README/发布说明里声称未经验证的采用、客户或效果。
- 用 stars、release 数量、检查数量当成功指标。
- 在 P0 期间改动 lifecycle surface 的功能。

## 发布

- 版本、CHANGELOG、`docs/releases/<version>.md`、README pin 必须一致
  （`tests/test_release_consistency.py` 会检查）。
- `scripts/release_prep.py` 之后必须人工看 diff。
- PyPI 版本不可变；先验证 wheel，再打 tag。
- 红分支不发布。

## 每个改动回答五个问题

1. 它增加每次判定的证据，还是降低判定的成本？
2. 第三方不重跑 agent 能不能复核输出？
3. 默认路径是否离线、无 key？
4. 是否缩短了主要用户到第一个判定的时间？
5. 是不是新 surface？如果是，谁（真实的人/仓库）要求的？
