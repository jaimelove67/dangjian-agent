# 测试业务数据清理

用于清理体验测试或联调留下的会议记录、个人材料和发展材料。清理只做软删除（`is_deleted=true`），不物理删除数据，不删除修订、审计、查阅回执或加密原件卷，并写入审计日志。

## 适用范围

- 仅允许在 `development` / `testing` 环境执行。
- 按记录编号逐条处理；不提供批量删除，避免误伤真实业务记录。
- 已归档会议、已审核材料也可以软删除，但记录仍保留在数据库中，可由维护人员核对审计。

## 使用步骤

在仓库根目录执行，使用已安装后端依赖的 Python：

```powershell
# 1. 预演：只打印将处理的记录，不写库
python backend/scripts/cleanup_test_records.py `
  --actor <管理员登录账号> `
  --reason "清理体验测试数据" `
  --meeting-id <会议编号> `
  --personal-material-id <个人材料编号> `
  --development-material-id <发展材料编号>

# 2. 核对预演结果后执行软删除
python backend/scripts/cleanup_test_records.py `
  --actor <管理员登录账号> `
  --reason "清理体验测试数据" `
  --meeting-id <会议编号> `
  --personal-material-id <个人材料编号> `
  --development-material-id <发展材料编号> `
  --confirm
```

三个编号至少提供一个。个人材料与发展材料使用同一个 `member_materials` 表，脚本会按 `user_id` / `submission_key` 区分，传错类型会直接拒绝。

## 记录编号从哪里来

- 会议记录：会议详情或接口响应中的记录编号。
- 个人材料：本人材料详情或材料接收接口中的材料编号。
- 发展材料：党员发展材料清单中的材料编号。

脚本不会按标题模糊匹配，也不接受姓名或组织名称，避免误删同名记录。执行前请自行备份数据库。
