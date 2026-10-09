import {
  appCopyrightPreferences,
  defineOverridesPreferences,
} from '@vben/preferences';

/**
 * @description 项目配置文件
 * 只需要覆盖项目中的一部分配置，不需要的配置不用覆盖，会自动使用默认配置
 * !!! 更改配置后请清空缓存，否则可能不生效
 */
export const overridesPreferences = defineOverridesPreferences({
  // overrides
  app: {
    name: import.meta.env.VITE_APP_TITLE,
    /**
     * 权限模式：
     * - frontend：菜单由前端路由文件生成（当前）
     * - backend：菜单由后端接口下发，对应 src/api/core/menu.ts 的 getAllMenusApi
     *   后端补齐菜单接口后可切换为 backend，以匹配「菜单由配置生成」的设计
     */
    accessMode: 'frontend',
  },
  copyright: appCopyrightPreferences,
  theme: {
    /** 党建红 */
    colorPrimary: 'hsl(0 57% 41%)',
    /** 党建类系统按浅色交付 */
    mode: 'light',
  },
});
