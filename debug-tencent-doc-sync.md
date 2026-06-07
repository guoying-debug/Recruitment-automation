# Debug Session: tencent-doc-sync [OPEN]

## Bug Summary
- 症状：页面显示“已同步腾讯文档”，但目标腾讯文档表格中没有候选人数据。
- 目标：拿到腾讯文档真实运行时响应，确认是请求未发出、请求失败、响应误判，还是写入参数错误。

## Hypotheses
- H1: `batchUpdate` 请求实际返回了错误，但前端同步状态判断过于宽松，误记为成功。
- H2: 请求头或鉴权字段格式不符合腾讯文档要求，导致接口未真正执行写入。
- H3: `updateRangeRequest` 的请求体字段名或数据结构不符合接口要求，接口拒绝写入。
- H4: `sheetId`、`range` 或目标工作表定位错误，请求成功但没有写到当前看到的表格区域。
- H5: 本地写入候选人 CSV 的时间点早于腾讯文档同步结果确认，导致“已同步”状态与真实外部结果不一致。

## Evidence Plan
- 为腾讯文档请求增加最小化运行时日志：请求 URL、headers 中非敏感字段、sheetId、range、响应状态码、响应体。
- 为同步结果记录增加前后状态日志：调用前、调用后、入库前的判定链路。
- 复现一次“批量处理并同步”，用日志证伪上述假设。

## Evidence
- Pre-fix 日志显示：HTTP 200，但响应体为 `{"responses":[{"updateRangeResponse":{"updatedCells":0}}]}`。
- Pre-fix 日志显示：旧逻辑仍将 `updatedCells: 0` 判定为 `is_success: true`。
- Post-fix 日志显示：同样的响应现在被判定为 `is_success: false`，并返回明确错误信息。
- 额外联调结果：官方 V2 `更新区域内容` 接口在完成 fileID 转换后返回 `{"ret":10007,"msg":"No corresponding permissions required"}`，说明当前授权大概率缺少写入权限。

## Analysis
- H1 confirmed: 旧代码把“有 responses 字段”误认为同步成功，导致页面误报“已同步腾讯文档”。
- H2 rejected: 请求头三元组存在，且接口未返回 401/10302/10303 这类典型鉴权错误。
- H3 inconclusive: V3 `batchUpdate` 请求体是否完全符合预期仍需腾讯文档更细文档确认，但当前最直接证据是 `updatedCells=0`。
- H4 partially rejected: `sheetId=BB08J2`、`range=A3:L3` 已被服务端接受；若完全非法应直接报参数错误。
- H5 confirmed: 本地状态更新依赖旧的宽松成功判定，早于真实“写入生效”确认。

## Fix
- 将腾讯文档同步成功条件收紧为：`updateRangeResponse.updatedCells > 0`。
- 增加 `last_error`，在未写入任何单元格时保留可读错误信息。
- 保留调试插桩，用于后续继续验证权限或 payload 结构。

## Current Status
- 代码侧误报问题已修复。
- 外部根因大概率为腾讯文档应用未获得 `scope.sheet / scope.sheet.editable` 写权限，或当前 token 未携带对应 scope。
- 调试会话保持开启，等待用户确认是否继续处理权限授权问题。
