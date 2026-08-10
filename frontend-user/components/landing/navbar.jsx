"use client";

import { useState, useEffect } from "react"
import Link from 'next/link';
import { usePathname } from 'next/navigation'
import { Menu, X, Sun, Moon, ChevronDown } from "lucide-react"
import { Button } from "@/components/landing/ui/button"
import { InstallPwaButton } from "@/components/common/InstallPwaButton"
import { useTheme } from "@/context/ThemeContext"
import { StockExLogo } from "@/components/StockExLogo"
import { useBranding } from "@/lib/branding-context"
import { API_URL } from "@/lib/constants"

// Every menu item now resolves to a real page. The parents used to be
// homepage anchors (`/#markets`, `/#platform`, `/#accounts`), which meant
// "Trading" and "Platforms" could only ever scroll you down the homepage
// and had no destination of their own. They point at dedicated hub pages
// instead, each of which fans out to the detail pages below it.
//
// Accounts lives at /account-types, NOT /accounts — the dashboard already
// owns /accounts (app/(dashboard)/accounts), and a second route at that
// path is a build-time collision in Next.
const navLinks = [
  { href: "/", label: "Home" },
  {
    href: "/trading",
    label: "Trading",
    children: [
      { href: "/equity", label: "Equity" },
      { href: "/futures-options", label: "Futures & Options" },
      { href: "/commodities", label: "Commodities" },
      { href: "/indices", label: "Indices" },
    ],
  },
  {
    href: "/platforms",
    label: "Platforms",
    children: [
      { href: "/standard", label: "Standard" },
      { href: "/pro", label: "Pro" },
      { href: "/demo", label: "Demo" },
    ],
  },
  { href: "/account-types", label: "Accounts" },
  { href: "/education", label: "Education" },
  { href: "/nifty-games", label: "Nifty Games" },
  { href: "/about", label: "About" },
  { href: "/contact", label: "Contact" },
]

/* Shared class for every pill-shaped nav item, so the active / idle /
   dropdown states can't drift apart. Ink bar → light labels, lime for
   the current page. */
const navItemBase =
  "px-3 py-2 rounded-full text-[13px] font-medium tracking-[-0.01em] transition-colors duration-200"
const navItemIdle = "text-white/65 hover:text-white hover:bg-white/[0.08]"
const navItemActive = "bg-[#C6F642] text-[#101210]"

/* InstallPwaButton's compact variant defaults to `text-primary` on a
   `bg-primary/10` chip. That reads correctly on the light card it uses on
   the login page, but `--primary` is INK inside the landing scope and this
   nav bar is ink too — so the button rendered dark-on-dark and effectively
   disappeared. Both nav placements sit on a dark surface, so override to
   the same white-alpha treatment the other secondary nav items use.
   `cn()` runs through tailwind-merge, so these replace the defaults rather
   than stacking with them. */
const installBtn =
  "border-white/20 bg-white/[0.06] text-white/80 hover:bg-white/[0.12] hover:text-white"

export function Navbar({ embedded = false }) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  // Which parent group is expanded in the mobile accordion.
  const [openGroup, setOpenGroup] = useState(null)
  const pathname = usePathname()
  const { theme, toggleTheme, isDark } = useTheme()

  // White-label branding. This came across from MarketingNav when the two
  // navs were merged — tenants on a custom domain get their own logo and
  // name, and dropping it would have silently rebranded every one of them
  // back to StockEx on the marketing pages.
  const { branding } = useBranding()
  const customName = (branding?.brand_name ?? "").trim()
  const logoSrc = branding?.logo_url ? `${API_URL}${branding.logo_url}` : null

  // Close the menu on navigation so a route change never leaves the
  // mobile panel hanging open over the new page.
  useEffect(() => {
    setIsMobileMenuOpen(false)
    setOpenGroup(null)
  }, [pathname])

  // Hash links ("/#markets") must NOT mark Home active just because the
  // pathname is "/", and must not all light up at once. Only compare the
  // path portion, and treat pure-hash entries as never "current".
  const isActive = (href) => {
    if (href.includes("#")) return false
    return href === "/" ? pathname === "/" : pathname?.startsWith(href)
  }

  return (
    <header
      className={
        embedded
          ? "relative pt-4 px-4"
          : "fixed top-0 left-0 right-0 z-50 pt-4 px-4"
      }
    >
      <div className="max-w-7xl mx-auto">
        {/* Floating Pill Navbar */}
        <nav className="bg-[#141614]/95 backdrop-blur-xl border border-white/[0.08] rounded-full px-2 py-2 flex items-center justify-between gap-2">
          {/* Logo */}
          <Link href="/" className="flex shrink-0 items-center gap-2.5 pl-2">
            {logoSrc ? (
              <>
                <span className="grid size-9 place-items-center rounded-xl bg-white/[0.08]">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={logoSrc}
                    alt={customName || "Logo"}
                    className="size-6 rounded object-contain"
                  />
                </span>
                <span className="font-display text-lg font-bold tracking-tight text-white">
                  {customName || "StockEx"}
                </span>
              </>
            ) : (
              <StockExLogo className="h-9 w-auto" alt={customName || "StockEx"} />
            )}
          </Link>

          {/* Desktop Navigation Links */}
          <div className="hidden lg:flex items-center gap-0.5">
            {navLinks.map((link) => {
              const active = isActive(link.href)

              if (link.children) {
                return (
                  // Hover-opened panel. `pt-2` on the wrapper bridges the
                  // gap between trigger and panel so the pointer can travel
                  // into the menu without it closing underneath.
                  <div key={link.href} className="group relative">
                    <Link
                      href={link.href}
                      className={`${navItemBase} ${active ? navItemActive : navItemIdle} inline-flex items-center gap-1`}
                    >
                      {link.label}
                      <ChevronDown className="w-3.5 h-3.5 transition-transform duration-200 group-hover:rotate-180" />
                    </Link>
                    <div className="invisible absolute left-0 top-full pt-2 opacity-0 transition-all duration-150 group-hover:visible group-hover:opacity-100">
                      <div className="min-w-[210px] rounded-2xl bg-[#181B18] border border-white/[0.08] p-2 shadow-[0_16px_48px_-16px_rgba(0,0,0,0.6)]">
                        {link.children.map((child) => (
                          <Link
                            key={child.href}
                            href={child.href}
                            className="block rounded-xl px-3 py-2 text-[13px] font-medium text-white/70 transition-colors hover:bg-white/[0.06] hover:text-[#C6F642]"
                          >
                            {child.label}
                          </Link>
                        ))}
                      </div>
                    </div>
                  </div>
                )
              }

              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`${navItemBase} ${active ? navItemActive : navItemIdle}`}
                >
                  {link.label}
                </Link>
              )
            })}
          </div>

          {/* Desktop CTA Buttons */}
          <div className="hidden lg:flex shrink-0 items-center gap-1.5 pr-1">
            {/* Theme Toggle Button */}
            <button
              onClick={toggleTheme}
              className="p-2 rounded-full text-white/60 hover:text-white hover:bg-white/[0.08] transition-colors"
              aria-label="Toggle theme"
            >
              {isDark ? <Sun className="w-[18px] h-[18px]" /> : <Moon className="w-[18px] h-[18px]" />}
            </button>
            <InstallPwaButton variant="compact" className={installBtn} />
            <Link href="/login">
              <Button
                variant="ghost"
                className="text-[13px] font-medium text-white/70 hover:text-white hover:bg-white/[0.08] rounded-full"
              >
                Log In
              </Button>
            </Link>
            <Link href="/login?register=true">
              <Button className="bg-[#C6F642] hover:bg-[#b8ea2e] text-[#101210] text-[13px] font-semibold px-5 rounded-full transition-colors">
                Open Account
              </Button>
            </Link>
          </div>

          {/* Mobile Menu Button */}
          <button
            className="lg:hidden p-2 mr-1 text-white/80"
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            aria-label={isMobileMenuOpen ? "Close menu" : "Open menu"}
            aria-expanded={isMobileMenuOpen}
          >
            {isMobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </nav>

        {/* Mobile Menu */}
        {isMobileMenuOpen && (
          <div className="lg:hidden mt-2 bg-[#141614]/97 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-3">
            <nav className="flex flex-col gap-0.5">
              {navLinks.map((link) => {
                const active = isActive(link.href)

                // Parent with children → collapsible accordion row.
                if (link.children) {
                  const expanded = openGroup === link.href
                  return (
                    <div key={link.href}>
                      <button
                        type="button"
                        onClick={() =>
                          setOpenGroup((g) => (g === link.href ? null : link.href))
                        }
                        aria-expanded={expanded}
                        className={`flex w-full items-center justify-between rounded-xl px-4 py-3 text-sm font-medium transition-colors ${
                          expanded
                            ? "bg-white/[0.08] text-white"
                            : "text-white/70 hover:text-white hover:bg-white/[0.08]"
                        }`}
                      >
                        {link.label}
                        <ChevronDown
                          className={`w-4 h-4 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
                        />
                      </button>
                      {expanded && (
                        <div className="ml-3 mt-1 flex flex-col gap-0.5 border-l border-white/[0.08] pl-3">
                          {link.children.map((child) => (
                            <Link
                              key={child.href}
                              href={child.href}
                              className="rounded-xl px-4 py-2.5 text-sm text-white/60 transition-colors hover:bg-white/[0.06] hover:text-[#C6F642]"
                              onClick={() => setIsMobileMenuOpen(false)}
                            >
                              {child.label}
                            </Link>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                }

                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={`block rounded-xl px-4 py-3 text-sm font-medium transition-colors ${
                      active
                        ? "bg-[#C6F642] text-[#101210]"
                        : "text-white/70 hover:text-white hover:bg-white/[0.08]"
                    }`}
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    {link.label}
                  </Link>
                )
              })}

              <div className="flex flex-col gap-2.5 pt-4 mt-2 border-t border-white/[0.08]">
                {/* Mobile Theme Toggle */}
                <button
                  onClick={toggleTheme}
                  className="flex items-center justify-between py-3 px-4 rounded-xl text-white/70 hover:text-white hover:bg-white/[0.08] transition-colors"
                >
                  <span className="text-sm font-medium">
                    {isDark ? 'Light Mode' : 'Dark Mode'}
                  </span>
                  {isDark ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
                </button>
                <InstallPwaButton
                  variant="compact"
                  className={`w-full justify-center py-2.5 ${installBtn}`}
                />
                <Link href="/login" onClick={() => setIsMobileMenuOpen(false)}>
                  <Button
                    variant="outline"
                    className="w-full rounded-full border-white/20 bg-transparent text-white hover:bg-white/[0.08] hover:text-white"
                  >
                    Log In
                  </Button>
                </Link>
                <Link href="/login?register=true" onClick={() => setIsMobileMenuOpen(false)}>
                  <Button className="w-full bg-[#C6F642] hover:bg-[#b8ea2e] text-[#101210] font-semibold rounded-full transition-colors">
                    Open Account
                  </Button>
                </Link>
              </div>
            </nav>
          </div>
        )}
      </div>
    </header>
  )
}
