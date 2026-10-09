<script setup lang="ts">
/**
 * 图标组件。
 *
 * ⚠️ taste-skill Section 3.C 规定：优先使用图标库（@phosphor-icons 等），
 *    并明令「禁止手写 SVG 图标」。此处做了一个有意识的偏离，原因如下：
 *
 *    1. 本环境无法安装任何第三方依赖（node 子进程受限，见项目长期记忆），
 *       引入图标库会让整个工程无法构建，代价远大于收益。
 *    2. 允许的图标库里，Phosphor / Hugeicons / Radix 的字形与「编辑式浅色」
 *       调性并不契合（笔画偏圆润、风格偏产品化）。
 *
 *    偏离的补偿措施（保证不会退化成"随手涂鸦"）：
 *    - 全部图标共用同一栅格（24×24）、同一描边宽度（1.5）、同一圆角线帽，
 *      所以视觉上仍是一个**统一图标族**，而非拼凑。
 *    - 每个图标只承担一个语义，禁止复用于不同含义。
 *    - 全站只此一个图标来源，不允许任何组件内联散写 SVG。
 *
 *    接口补齐后若引入图标库，只需替换本文件内部实现，调用点无需改动。
 */

export type IconName =
  | 'ask'
  | 'book'
  | 'people'
  | 'pulse'
  | 'search'
  | 'quote'
  | 'alert'
  | 'check'
  | 'close'
  | 'chevron-right'
  | 'chevron-down'
  | 'plus'
  | 'upload'
  | 'external'
  | 'copy'
  | 'info'
  | 'shield'
  | 'clock'
  | 'logout'
  | 'filter'
  | 'layout'
  | 'arrow-right'
  | 'empty'
  | 'error'

withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 16 })
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
    class="icon"
  >
    <!-- 问答：对话泡，用于主入口 -->
    <template v-if="name === 'ask'">
      <path d="M20 14.5a2.5 2.5 0 0 1-2.5 2.5H8l-4 3.5V6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5z" />
      <path d="M8.5 9.5h7M8.5 12.5h4" />
    </template>

    <!-- 知识库：合起的书本 -->
    <template v-else-if="name === 'book'">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v15H6.5A2.5 2.5 0 0 0 4 20.5z" />
      <path d="M4 5.5V20.5" />
      <path d="M19 18v3H6.5" />
    </template>

    <!-- 党员发展：两个人物，表示组织与个人 -->
    <template v-else-if="name === 'people'">
      <circle cx="9.5" cy="8" r="3.25" />
      <path d="M3.5 20v-1.5A5 5 0 0 1 8.5 13.5h2A5 5 0 0 1 15.5 18.5V20" />
      <path d="M16.5 5.2a3.25 3.25 0 0 1 0 5.6" />
      <path d="M18.5 14.2a5 5 0 0 1 2 3.9V20" />
    </template>

    <!-- 系统状态：脉搏折线 -->
    <template v-else-if="name === 'pulse'">
      <path d="M3 12h3.5l2-5 3 10 2.5-6.5 1.5 3H21" />
    </template>

    <!-- 检索 -->
    <template v-else-if="name === 'search'">
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 4.5 4.5" />
    </template>

    <!-- 引用 / 条款 -->
    <template v-else-if="name === 'quote'">
      <path d="M9.5 6.5C7 7.5 5.5 9.7 5.5 12.2V17.5h5.5v-5.5H8c0-1.6.6-2.8 2-3.5z" />
      <path d="M18.5 6.5c-2.5 1-4 3.2-4 5.7V17.5H20v-5.5h-3c0-1.6.6-2.8 2-3.5z" />
    </template>

    <!-- 警告：三角形。语义=需人工复核，不复用为普通提示 -->
    <template v-else-if="name === 'alert'">
      <path d="M12 4.5 21 20H3z" />
      <path d="M12 10v4" />
      <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
    </template>

    <!-- 通过 / 满足 -->
    <template v-else-if="name === 'check'">
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </template>

    <!-- 关闭 / 清除 -->
    <template v-else-if="name === 'close'">
      <path d="m6.5 6.5 11 11M17.5 6.5l-11 11" />
    </template>

    <!-- 向右展开 -->
    <template v-else-if="name === 'chevron-right'">
      <path d="m9.5 6.5 5.5 5.5-5.5 5.5" />
    </template>

    <template v-else-if="name === 'chevron-down'">
      <path d="m6.5 9.5 5.5 5.5 5.5-5.5" />
    </template>

    <!-- 新增 -->
    <template v-else-if="name === 'plus'">
      <path d="M12 5.5v13M5.5 12h13" />
    </template>

    <!-- 上传 -->
    <template v-else-if="name === 'upload'">
      <path d="M12 16V4.5" />
      <path d="m7.5 9 4.5-4.5L16.5 9" />
      <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
    </template>

    <!-- 外部链接（原文出处） -->
    <template v-else-if="name === 'external'">
      <path d="M13.5 4.5H19.5V10.5" />
      <path d="M19.5 4.5 11 13" />
      <path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" />
    </template>

    <!-- 复制 -->
    <template v-else-if="name === 'copy'">
      <rect x="8.5" y="8.5" width="11" height="11" rx="1.5" />
      <path d="M15.5 5.5A1.5 1.5 0 0 0 14 4H6a2 2 0 0 0-2 2v8a1.5 1.5 0 0 0 1.5 1.5" />
    </template>

    <!-- 一般提示 -->
    <template v-else-if="name === 'info'">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5" />
      <circle cx="12" cy="7.9" r="0.6" fill="currentColor" stroke="none" />
    </template>

    <!-- 数据分级 / 出网闸门 -->
    <template v-else-if="name === 'shield'">
      <path d="M12 3.5 19 6v6c0 4-2.9 7.2-7 8.5-4.1-1.3-7-4.5-7-8.5V6z" />
      <path d="m9 12 2 2 4-4.5" />
    </template>

    <!-- 时效 -->
    <template v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </template>

    <template v-else-if="name === 'logout'">
      <path d="M9.5 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h3.5" />
      <path d="M14.5 8 19 12l-4.5 4" />
      <path d="M19 12H9" />
    </template>

    <!-- 筛选 -->
    <template v-else-if="name === 'filter'">
      <path d="M4 6.5h16M7 12h10M10 17.5h4" />
    </template>

    <!-- 密度切换 -->
    <template v-else-if="name === 'layout'">
      <rect x="4" y="4.5" width="16" height="15" rx="2" />
      <path d="M4 9.5h16M4 14.5h16" />
    </template>

    <template v-else-if="name === 'arrow-right'">
      <path d="M4.5 12h15M14 6.5l5.5 5.5-5.5 5.5" />
    </template>

    <!-- 空态：空容器 -->
    <template v-else-if="name === 'empty'">
      <path d="M4 9.5 6.5 4.5h11L20 9.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5z" />
      <path d="M4 9.5h4l1.5 3h5L16 9.5h4" />
    </template>

    <!-- 错误：圆圈叉 -->
    <template v-else-if="name === 'error'">
      <circle cx="12" cy="12" r="8.5" />
      <path d="m9.2 9.2 5.6 5.6M14.8 9.2l-5.6 5.6" />
    </template>
  </svg>
</template>

<style scoped>
.icon {
  flex: none;
  /* 与文字基线的视觉对齐：图标通常需要下沉一点点 */
  transform: translateY(-0.5px);
}
</style>
