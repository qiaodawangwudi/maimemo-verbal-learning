# 发布状态机

发布只能沿下列状态前进；任何输入变化都按失效规则回退。不要跨状态，也不要把聊天批准、脚本可用或令牌存在解释为状态迁移。

## 状态与转移

| 当前状态 | 进入下一状态所需工件 | 下一状态 | 失败动作 |
|---|---|---|---|
| `collecting_sources` | 有效 `source_inventory` | `building_semantics` | 停在来源清点 |
| `building_semantics` | 通过的 `semantic_registry` | `reconciling_library` | 报告待核义项或冲突 |
| `reconciling_library` | 绑定当前快照与语义档案的 `library_reconciliation` | `reviewing_discrimination` | 报告重复主卡、异形词、一词多义或新建证明缺失 |
| `reviewing_discrimination` | 通过的 `discrimination_review` | `reviewing_applications` | 报告比较组或根引用决定 |
| `reviewing_applications` | 通过的 `application_review` | `freezing_cards` | 报告非唯一题目 |
| `freezing_cards` | 有效 `frozen_cards` | `building_manifest` | 禁止继续编辑后假装已冻结 |
| `building_manifest` | 有效 `release_manifest` | `awaiting_github_authorization` | 报告范围、哈希或动作不一致 |
| `awaiting_github_authorization` | 匹配的 `github_authorization` | `writing` | 停止；无备用写入路径 |
| `writing` | 完整且确定的 `write_receipts` | `reading_back` | 转 `write_indeterminate` 或 `write_failed` |
| `reading_back` | 通过的 `readback_report` | `completed` | 转 `readback_failed` |

## 授权规则

GitHub 最终授权必须逐字段匹配发布清单的 `release_hash`、`chapter_ids` 和 `action_counts`。以下事件立即使授权失效并回到 `building_manifest`：

- 目标由一章改成三章或任何章节集合变化；
- 新增、删除、更新、复用或不动动作发生变化；
- 冻结卡片、顺序、标题、内容或引用变化；
- 全库快照变化；
- 发布哈希变化。

GitHub 授权请求失败、被拒、超时或无法验证时，保持 `awaiting_github_authorization`。不得存在本地备用写入路径；不得使用本地令牌、环境中偶然存在的凭证或聊天授权绕过状态机。

## 写入不确定性

对每个动作使用由 `release_hash + action_identity` 派生的稳定幂等键。写入后记录请求 ID、幂等键、目标、响应和回读 ID。

当 `POST` 超时、连接中断或响应不可解析：

1. 立即停止新的创建请求并进入 `write_indeterminate`。
2. 使用同一发布哈希、幂等键、预期标题和内容哈希执行全量回读。
3. 找到唯一匹配结果：补记回执，不再重试。
4. 找到多个或冲突结果：保持阻塞，输出精确冲突清单。
5. 可证明完全未写入：只允许重放完全相同的冻结请求与幂等键。
6. 无法证明：保持阻塞；不得立即重试创建。

## 全量回读

全量回读必须重新读取目标章节全部卡片，而不是只读响应中返回的 ID。核对：

- 章节 ID、名称与总数；
- 每张预期卡的标题、内容哈希、语法版本和顺序；
- 所有引用都是正确的 `mkjr_` 根 ID；
- 比较组覆盖完整；
- 每个计划动作有且仅有一个结果；
- 未计划新增、更新或删除数量为零。

只有 `readback_report.status == passed` 才能进入 `completed`。API 返回成功、部分回读成功或“没有发现明显问题”都不够。
