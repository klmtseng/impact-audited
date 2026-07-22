# 內部機械審計 — 多語言擴充(57878a0)+ GitNexus issue 草稿

日期:2026-07-23。威脅層:T1 + T2(兩者即將對外)。審計者:建造者本人(第 1 段;第 2 段獨立 reviewer 另跑)。

## 宣稱逐條

| # | 宣稱 | 判定 | 證據(實跑) | 恆真? |
|---|---|---|---|---|
| C1 | 多語言 floor + auto 偵測正確 | PASS | /tmp/ia-fixture 對抗 fixture:auto 偵測 go/py/rs/ts;a.py/b.rs/c.ts/d.go 入列、onlycomment.rs 正確排除;--lang rust 過濾正確;--lang cobol exit 3 | 可能 FAIL(fixture 特意含定義行/註解行陷阱) |
| C2 | 註解排除不誤殺真呼叫 | PASS(有已知限制) | 同上 fixture;行首註解排除、行中 trailing comment 保留 | 可能 FAIL |
| C3 | T1/T2/T3 驗收全過 | PASS | 本 session 實跑輸出(T1 self exit 0;T2 run_input 只剩 main.rs;T3 exit 2) | 可能 FAIL |
| C4 | GitNexus 1.6.3+1.6.9 漏報 sched.rs 邊 | PASS(強化) | 完整 JSON grep 'sched' 零出現;direct=2 實為 tools/mod.rs 兩個 #[cfg(test)] 函式;輸出自稱 epistemic:"exact" | 可能 FAIL(若 GitNexus 有報就翻案) |
| C5 | 與 #2604/#2508 根因不同 | PASS | #2604 本文明寫僅限 trait-object、其他 dispatch 形狀正常;#2508=read-filter 掉邊,草稿已標 unclear | 可能 FAIL |
| C6 | 重現指令乾淨狀態可跑 | PASS(alias 差異) | /tmp/noob-cli-fresh 全新 clone+1.6.9 索引:LOW/direct=2/processes=0 重現;唯 --name 改 noob-fresh 避本機 registry 衝突 | 可能 FAIL |
| C7 | FTS read-only → query 永久不可用 | **FAIL,撤回** | fresh 1.6.9 索引 query 正常回 processes;錯誤僅出現於 1.6.3 建的索引(升級路徑問題,未隔離根因)| — |

## 歷史挑戰回答

- [3] 恆真句:上表逐項標注;無恆真 PASS。
- [22] 重現交叉驗證:C4 用兩種寫法(audited 工具 file-path scan + 直接 grep JSON)一致。
- [23]/email 帳本:新 commit 57878a0 = klmtseng noreply ✅;但歷史 6 筆 tzuwei@local 已在公網(既存暴露,P2 報使用者裁決,非本次引入)。
- [24] 事實錨點:sched.rs:361 fn dispatch / :386 tools::dispatch 已 grep 重驗;版本號 1.6.3/1.6.9 皆實跑。
- [2] 引用:#2604/#2508 經 gh issue view 實讀。

## T2 系統項

- 交付物端到端:issue 重現指令從 fresh clone 實跑 ✅;README 新例未逐字實跑(與 T3 指令同構,標 P3)。
- push 阻礙:local/remote diverged(遠端多 aa07a83 LICENSE 統一 commit),push 前需 rebase。
- 不可重生資產:無(全部可重建)。

## 已知限制(不擋結案)

- 同名符號 floor 過近似(sse.rs 混入)——既有文件化限制,非本次引入。
- 跨語言註解標記聯集:py+rs 混合 repo 中 Rust `#[attr]` 行會被當註解排除(attr 行含呼叫式極罕見,P3)。
- 區塊註解內部不排除(docstring 已明示)。

## 更正動作

1. issue 草稿刪除 FTS「permanently unavailable」段(C7 撤回)。
2. 草稿重現指令與說明補 epistemic:"exact" 與 direct=2=測試函式 細節(強化)。

---

## 第 2 段:獨立 reviewer(opus,fresh context)結果

- **P1:0**。issue 草稿三宣稱逐字實跑重現(含 epistemic:"exact"、direct=2=測試函式、ambiguous 3 候選、行號引文比對)。
- **P2:2(均主線重現後修復,commit 1935d7a)**:
  1. grep floor 不剪 node_modules/target/.venv 而 detect_langs 剪 → vendored 呼叫點造成假 AUDIT FAILED。修:PRUNE_DIRS 共用 + grep --exclude-dir。
  2. files_in_text 丟絕對路徑 → 印絕對路徑的 backend 全數誤判 omitted。修:realpath 正規化為 root-relative,root 外忽略;連帶補相對路徑 normpath 與 ../ 防護。
- **P3:4**(trailing comment 未排除=文件已如實揭露;TS interface 簽名過近似;README「found 3」無假陽性 caveat 已修;#2604/#2508 狀態 reviewer 無網未核,主線已於審前以 gh 實讀補核)。
- 主線額外失手:迴歸腳本 `cmd | tail; echo $?` 讀到 pipe 末端 exit code,T3 誤讀為 0——帳本 [22] 同型第 2 次,已修測法並記 ledger。

## 終局

- 修復後全量迴歸 8/8 PASS(P2×3 案例、escape-root 防護、fixture、T1/T2/T3)。
- C7(FTS)撤回並自草稿移除;C1–C6 成立。
- ledger append ×3(a/b/c)。
- **裁決:T1/T2 過。兩項對外(push repo、發 issue)技術上就緒,執行仍待使用者明示。**
