"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/fund-flow", label: "资金面 / 筹码" },
  { href: "/limit-up", label: "打板" },
  { href: "/daily-review", label: "每日复盘" },
];

export function TopNav() {
  const pathname = usePathname();

  return (
    <nav className="top-nav" aria-label="主导航">
      {items.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={active ? "nav-link active" : "nav-link"}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
