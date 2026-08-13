import type { ElementType, ReactNode } from "react";

type MotionProps = {
  children?: ReactNode;
  initial?: unknown;
  animate?: unknown;
  exit?: unknown;
  transition?: unknown;
  whileInView?: unknown;
  viewport?: unknown;
  [key: string]: unknown;
};

function element(tag: ElementType) {
  return function StaticMotion({
    initial: _initial,
    animate: _animate,
    exit: _exit,
    transition: _transition,
    whileInView: _whileInView,
    viewport: _viewport,
    ...props
  }: MotionProps) {
    const Tag = tag;
    return <Tag {...props} />;
  };
}

export const motion = {
  article: element("article"),
  div: element("div"),
  figure: element("figure"),
  p: element("p"),
};

export function AnimatePresence({ children }: { children?: ReactNode; mode?: string }) {
  return children;
}
