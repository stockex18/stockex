
import { useState, useEffect } from "react"
import Link from 'next/link';
import { usePathname } from 'next/navigation'
import { Menu, X, Sun, Moon, ChevronDown, Gamepad2 } from "lucide-react"
import { Button } from "@/components/landing/ui/button"
import { InstallPwaButton } from "@/components/common/InstallPwaButton"
import { useTheme } from "@/context/ThemeContext"
import { StockExLogo } from "@/components/StockExLogo"

const navLinks = [
  { href: "/", label: "Home" },
  { href: "/markets", label: "Markets" },
  { href: "/accounts", label: "Accounts" },
  { href: "/demo-trading", label: "Demo Trading" },
  { href: "/broker-program", label: "Broker Program" },
]

export function Navbar({ embedded = false }) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [featuresOpen, setFeaturesOpen] = useState(false)
  const [mobileFeaturesOpen, setMobileFeaturesOpen] = useState(false)
  const pathname = usePathname()
  const { theme, toggleTheme, isDark } = useTheme()

  const featuresItems = [
    { href: "/features/games", label: "Nifty Games", icon: Gamepad2 },
  ]

  return (
    <header
      className={
        embedded
          ? "relative pt-4 px-4"
          : "fixed top-0 left-0 right-0 z-50 pt-4 px-4"
      }
    >
      <div className="max-w-6xl mx-auto">
        {/* Floating Pill Navbar */}
        <nav className="bg-white rounded-full shadow-lg px-2 py-2 flex items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex items-center pl-2">
            <StockExLogo className="h-9 w-auto" alt="StockEx" />
          </Link>

          {/* Desktop Navigation Links */}
          <div className="hidden lg:flex items-center gap-1">
            {navLinks.map((link) => {
              const isActive = pathname === link.href
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`px-4 py-2 rounded-full text-sm font-medium transition-all duration-200 ${
                    isActive 
                      ? "bg-yellow-accent text-deep-blue" 
                      : "text-gray-700 hover:bg-gray-100"
                  }`}
                >
                  {link.label}
                </Link>
              )
            })}
          </div>

          {/* Features Dropdown - Desktop */}
          <div className="hidden lg:block relative">
            <button
              onClick={() => setFeaturesOpen(!featuresOpen)}
              onBlur={() => setTimeout(() => setFeaturesOpen(false), 150)}
              className={`px-4 py-2 rounded-full text-sm font-medium transition-all duration-200 flex items-center gap-1 ${
                pathname.startsWith('/features')
                  ? "bg-yellow-accent text-deep-blue"
                  : "text-gray-700 hover:bg-gray-100"
              }`}
            >
              Features
              <ChevronDown className={`w-4 h-4 transition-transform duration-200 ${featuresOpen ? 'rotate-180' : ''}`} />
            </button>
            {featuresOpen && (
              <div className="absolute top-full left-0 mt-2 w-48 bg-white rounded-xl shadow-lg border border-gray-100 py-2 z-[9999]">
                {featuresItems.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-center gap-2.5 px-4 py-2.5 text-sm font-medium transition-colors ${
                      pathname === item.href
                        ? "bg-yellow-accent/10 text-deep-blue"
                        : "text-gray-700 hover:bg-gray-50"
                    }`}
                    onClick={() => setFeaturesOpen(false)}
                  >
                    <item.icon className="w-4 h-4 text-gray-500" />
                    {item.label}
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Desktop CTA Buttons */}
          <div className="hidden lg:flex items-center gap-2 pr-2">
            {/* Theme Toggle Button */}
            <button
              onClick={toggleTheme}
              className="p-2 rounded-full hover:bg-gray-100 transition-colors"
              aria-label="Toggle theme"
            >
              {isDark ? (
                <Sun className="w-5 h-5 text-yellow-500" />
              ) : (
                <Moon className="w-5 h-5 text-gray-700" />
              )}
            </button>
            <InstallPwaButton variant="compact" />
            <Link href="/login">
              <Button variant="ghost" className="text-sm font-medium text-gray-700 hover:text-deep-blue rounded-full">
                Log In
              </Button>
            </Link>
            <Link href="/login?register=true">
              <Button className="bg-yellow-accent hover:bg-yellow-500 text-deep-blue font-semibold px-5 rounded-full">
                Open Account
              </Button>
            </Link>
          </div>

          {/* Mobile Menu Button */}
          <button
            className="lg:hidden p-2 mr-1"
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            aria-label="Toggle menu"
          >
            {isMobileMenuOpen ? (
              <X className="w-6 h-6 text-gray-700" />
            ) : (
              <Menu className="w-6 h-6 text-gray-700" />
            )}
          </button>
        </nav>

        {/* Mobile Menu */}
        {isMobileMenuOpen && (
          <div className="lg:hidden mt-2 bg-white rounded-2xl shadow-lg p-4">
            <nav className="flex flex-col gap-1">
              {navLinks.map((link) => {
                const isActive = pathname === link.href
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={`block text-sm font-medium py-3 px-4 rounded-xl transition-colors ${
                      isActive 
                        ? "bg-yellow-accent text-deep-blue" 
                        : "text-gray-700 hover:bg-gray-100"
                    }`}
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    {link.label}
                  </Link>
                )
              })}
              {/* Mobile Features Dropdown */}
              <button
                onClick={() => setMobileFeaturesOpen(!mobileFeaturesOpen)}
                className={`flex items-center justify-between text-sm font-medium py-3 px-4 rounded-xl transition-colors w-full ${
                  pathname.startsWith('/features')
                    ? "bg-yellow-accent text-deep-blue"
                    : "text-gray-700 hover:bg-gray-100"
                }`}
              >
                Features
                <ChevronDown className={`w-4 h-4 transition-transform duration-200 ${mobileFeaturesOpen ? 'rotate-180' : ''}`} />
              </button>
              {mobileFeaturesOpen && (
                <div className="pl-4">
                  {featuresItems.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`flex items-center gap-2.5 text-sm font-medium py-2.5 px-4 rounded-xl transition-colors ${
                        pathname === item.href
                          ? "bg-yellow-accent/20 text-deep-blue"
                          : "text-gray-600 hover:bg-gray-50"
                      }`}
                      onClick={() => { setIsMobileMenuOpen(false); setMobileFeaturesOpen(false); }}
                    >
                      <item.icon className="w-4 h-4" />
                      {item.label}
                    </Link>
                  ))}
                </div>
              )}
              <div className="flex flex-col gap-3 pt-4 mt-2 border-t border-gray-100">
                {/* Mobile Theme Toggle */}
                <button
                  onClick={toggleTheme}
                  className="flex items-center justify-between py-3 px-4 rounded-xl hover:bg-gray-100 transition-colors"
                >
                  <span className="text-sm font-medium text-gray-700">
                    {isDark ? 'Light Mode' : 'Dark Mode'}
                  </span>
                  {isDark ? (
                    <Sun className="w-5 h-5 text-yellow-500" />
                  ) : (
                    <Moon className="w-5 h-5 text-gray-700" />
                  )}
                </button>
                <InstallPwaButton variant="compact" className="w-full justify-center" />
                <Link href="/login" onClick={() => setIsMobileMenuOpen(false)}>
                  <Button variant="outline" className="w-full rounded-full">Log In</Button>
                </Link>
                <Link href="/login?register=true" onClick={() => setIsMobileMenuOpen(false)}>
                  <Button className="w-full bg-yellow-accent hover:bg-yellow-500 text-deep-blue font-semibold rounded-full">Open Account</Button>
                </Link>
              </div>
            </nav>
          </div>
        )}
      </div>
    </header>
  )
}
