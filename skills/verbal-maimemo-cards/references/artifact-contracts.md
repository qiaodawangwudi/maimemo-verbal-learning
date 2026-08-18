# 工件契约

十阶段通过显式工件衔接。每个工件至少包含 `schema_version`、`created_at`、`input_hashes`、`status` 和可定位的 `errors`。只有 `status: passed` 的前置工件可被后继阶段消费。

## 工件一览

| 工件 | 必要字段 | 有效条件 |
|---|---|---|
| `source_inventory` | `source_groups[]`, `source_kind`, `locations`, `content_hash`, `access_scope` | 所有输入已清点；同源多版本已合组；证据可定位 |
| `semantic_registry` | `term`, `sense_id`, `meaning`, `distinctive_feature`, `evidence[]`, `status` | 每个结论有证据；无 `pending` / `conflict` |
| `library_reconciliation` | `snapshot_hash`, `semantic_registry_hash`, `entries[]`, `decision`, `canonical_card_id`, `retire_card_ids`, `reconciliation_hash` | 覆盖每个词面＋义项；新建有零候选证明；多卡和多义项无待决项 |
| `discrimination_review` | `group_key`, `members[]`, `sense_ids[]`, `minimum_differences[]`, `root_decision` | 完整组已重建；每条差异可判别；根引用决策有身份依据 |
| `application_review` | `prompt`, `options[]`, `best_option`, `exclusions[]`, `uniqueness_evidence`, `status` | 恰有一个最佳选项；逐项排除其余选项 |
| `frozen_cards` | `cards[]`, `order`, `card_hashes`, `frozen_cards_hash` | 卡片内容、顺序、标题和引用目标全部不可变 |
| `release_manifest` | `chapter_ids[]`, `snapshot_hash`, `frozen_cards_hash`, `actions[]`, `action_counts`, `release_hash` | 只引用已冻结卡片；动作与计数一致；无人工待决项 |
| `github_authorization` | `release_hash`, `chapter_ids[]`, `action_counts`, `authorized_at`, `actor`, `status` | 来自最终 GitHub 授权且与发布清单逐字段一致 |
| `write_receipts` | `release_hash`, `idempotency_keys[]`, `request_results[]`, `written_ids[]`, `status` | 每个动作可追踪；无结果不确定项 |
| `readback_report` | `chapter_ids[]`, `expected`, `actual`, `mismatches[]`, `unexpected_delta`, `status` | 全量而非增量回读；零不匹配、零未计划增量 |

## 哈希与失效

使用规范序列化后的内容计算哈希；排除生成时间等非语义字段。固定键顺序、卡片顺序、组内成员顺序和数组语义，确保同一载荷得到同一哈希。

以下任一变化必须重建下游工件：

- 来源内容或证据定位变化：从 `semantic_registry` 重建。
- 全库快照、规范词面、义项、主卡或重复卡处置变化：重建 `library_reconciliation`。
- 词义、特别之处、成员、义项或最小差别变化：从 `discrimination_review` 重建。
- 应用题、答案或排除理由变化：从 `application_review` 重建。
- 卡片内容、顺序、标题或引用变化：重新冻结并重建发布清单。
- 章节集合、动作或动作总数变化：重建 `release_manifest` 并重新授权。

`release_hash` 必须覆盖 `chapter_ids`、`snapshot_hash`、`frozen_cards_hash`、完整动作列表和动作总数。发布哈希变化后旧授权失效；不得复制、延长或口头扩展旧授权。

## 比较组与根引用

比较组身份键至少覆盖排序后的 `sense_ids` 与比较关系版本。成员重叠、标题相似或旧卡已有 `root_id` 都不是同组证明。

- 身份完全一致且只是对同一冻结组执行幂等更新：可沿用已核验根引用。
- 成员、义项或关系变化：重建完整组；写入辨析卡后回读真实 `mkjr_` 根 ID，再冻结依赖它的基础卡。
- 无法证明身份：将 `root_decision.status` 标为 `blocked`，不猜测复用。

## 写入器边界

写入器输入只允许 `release_manifest` 指向的冻结载荷、GitHub 授权和幂等键。写入器不得生成内容，也不得调用模型补全、重新渲染、改写字段或重排记录。任何修订必须退回相应审查阶段并产生新哈希。
