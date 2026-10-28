interface Point {
  x: number;
  y: number;
}

interface Size {
  width: number;
  height: number;
}

/** 菜单放在点击处；靠近窗口右边或底边时收回窗口内（留 8 像素边距），不被截掉。 */
export function clampToViewport(point: Point, menu: Size, viewport: Size, margin = 8): Point {
  return {
    x: Math.max(margin, Math.min(point.x, viewport.width - menu.width - margin)),
    y: Math.max(margin, Math.min(point.y, viewport.height - menu.height - margin)),
  };
}
