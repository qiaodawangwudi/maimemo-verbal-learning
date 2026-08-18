# 执行入口

本 Skill 自带完整运行时、受保护 GitHub 工作流模板和统一入口，不依赖原开发仓库。使用当前 Skill 路径调用：

```text
python scripts/run_pipeline.py self-check
```

只有返回 `status: passed`，才能继续。统一入口的阶段命令为：

| 阶段命令 | 对应工作 |
|---|---|
| `collect-sources` | 清点、合并和定位来源 |
| `review-semantics` | 建立并审查词义档案 |
| `build-groups` | 重建完整近义比较组 |
| `build-applications` | 生成候选应用题 |
| `review-applications` | 独立审查答案唯一性 |
| `build-plan` | 生成冻结后的动作计划 |
| `public-preflight` | 检查公开发布边界 |
| `release-quality` | 核验发布质量与独立审查 |
| `authorize` | 核验最终 GitHub 授权 |
| `write-release` | 按冻结载荷写入并回读 |

把阶段自身参数写在命令后面。例如：

```text
python scripts/run_pipeline.py review-applications --artifact-dir <工件目录>
```

## 三种模式

### 只审查

运行来源、语义、辨析和应用审查，输出问题清单；不冻结、不生成发布授权、不读取令牌、不调用写接口。

### 生成预览

完成全部学习质量审查并生成基本词义、近义辨析、场景应用三类预览；停在冻结或发布清单之前，不调用写接口。

### 受保护发布

完成审查后冻结卡片，生成与章节、动作和快照绑定的发布清单。只有 GitHub 受保护环境的最终授权通过，才能调用 `write-release`；写后必须全量回读。

## 为目标仓库安装保护模板

在目标 Git 仓库中执行：

```text
python scripts/run_pipeline.py install-github-templates --target <目标仓库>
```

该命令安装 `CODEOWNERS`、学习质量检查和最终发布工作流。若目标文件已有不同内容，默认拒绝覆盖；只有用户明确要求替换时才使用 `--force`。目标仓库仍须提供与自身工件相符的测试，缺少测试时 GitHub 检查应失败关闭。

## 停止边界

- `self-check` 失败；
- 任一前置工件不是 `passed`；
- 词义、辨析或应用唯一性仍待核；
- 冻结内容、章节、动作或快照发生变化；
- GitHub 授权与发布哈希不匹配；
- 写入结果不确定且尚未全量回读。

上述情况不得另写临时脚本、寻找本地令牌或跳过阶段。
