import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '求职进度中心',
  description: '本机私有的投递进度、面试状态与表单资料缺口控制台',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
