# TODO

我建议做成“WARNING + 必须确认 + 后端兜底”这套，而不是只弹一个前端提示。现在线路里，历史 GTC 本来就会被算进有效挂单，repositories.py (line 57) 和 import_service.py (line 181) 已经这么做了；问题是前端当前有 WARNING 也会直接提交，ImportTab.tsx (line 503)。所以确认逻辑要补在提交链路里，前后端一起收口。

规则

卖出：当新增 DAY 卖单本身不超过总可卖仓位，但被“已生效的历史 GTC 卖单”占用了份额时，不再给 ERROR，改成“需确认的 WARNING”。
卖出：如果本身就超过总可卖仓位，仍然是 ERROR，这个不该靠确认放行。
买入：只要账户上存在已生效的 GTC 买单，新增买单就给“需确认的 WARNING”，哪怕当前现金仍然够，也让用户明确知道有老的持续买单在占用意图资金。
买入：如果单笔委托本身就超过账户可用现金，仍然是 ERROR；如果是和现有买单合计后可能超出，维持 WARNING，但同时标记为“需确认”。
接口与后端

在 schemas.py (line 118) 给 ImportPreviewResponse 增加批次级确认信息，推荐是：
confirmation: {
required: boolean;
token?: string;
items: Array<{
code: "SELL_DAY_BLOCKED_BY_GTC" | "BUY_HAS_ACTIVE_GTC";
summary: string;
rowNumbers: number[];
relatedOrders: Array<{
orderId: string;
tradeDate: string;
symbol: string;
side: "BUY" | "SELL";
price: number;
shares: int;
validity: "GTC";
}>;
}>;
}
在 schemas.py (line 168) 给 CommitImportsRequest 增加 confirmWarnings?: boolean 和 confirmationToken?: string。
在 import_service.py (line 181) / import_service.py (line 236) 把“普通 warning”和“需确认 warning”分开产出，不要靠解析 validationMessage 文案。
commit_import_batch 提交前继续重算一次确认项；如果当前仍存在需确认项，但请求里没有 confirmWarnings=true 或 confirmationToken 对不上，就返回 409，强制用户重新确认。
这个版本可以先不改库表。确认项和 token 都可以在 preview/commit 时现算，不必先落库。
前端交互

在 ImportTab.tsx (line 343) 的提交流程前，先重新 preview 一次，拿最新 batchId + confirmation。
如果有 confirmation.required=true，先不直接 commit，弹一个确认框；样式可以直接复用 CreateUserModal.tsx (line 1) 这套 modal。
弹窗里展示两类信息：
“这些新单会受哪些 GTC 影响”
“受影响的 GTC 挂单明细”
按钮建议只有两个：返回调整、确认提交。先不要做自动撤销 GTC，风险更低。
用户确认后，再调用 /imports/commit，把 confirmWarnings=true 和 confirmationToken 带上。
我推荐的 MVP 边界

先只做“确认后继续保留原 GTC”，不做“自动替换/自动撤销 GTC”。
卖出确认文案要写清楚：继续提交后，已有 GTC 会优先占用仓位，新 DAY 卖单后续可能被拒绝。
测试至少补 4 条：DAY SELL 被 GTC SELL 占仓触发确认、BUY 遇到 GTC BUY 触发确认、未确认提交被 409 拦住、确认后提交成功。
如果你认可，我下一步可以直接按这个 MVP 方案把前后端一起落掉。
