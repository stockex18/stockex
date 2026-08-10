import Link from 'next/link';
import { StockExLogo } from '@/components/StockExLogo'
import { Facebook, Twitter, Linkedin, Instagram, Youtube } from "lucide-react"


export function Footer() {
  return (
    <footer className="bg-white border-t border-[#E0E5E0]">
      {/* Main Footer */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20">
        <div className="flex flex-col items-center text-center">
          {/* Logo */}
          <Link href="/" className="flex items-center mb-5">
            <StockExLogo className="h-11 w-auto" alt="StockEx" />
          </Link>
          <p className="text-[15px] text-[#606862] mb-8">
            Trade India's Financial Markets
          </p>
          {/* Social Links */}
          <div className="flex gap-2">
            {[Facebook, Twitter, Linkedin, Instagram, Youtube].map((Icon, index) => (
              <Link
                key={index}
                href="#"
                className="w-10 h-10 rounded-full border border-[#E0E5E0] text-[#606862] flex items-center justify-center transition-colors hover:bg-[#141614] hover:border-[#141614] hover:text-white"
              >
                <Icon className="w-[18px] h-[18px]" />
              </Link>
            ))}
          </div>
        </div>
      </div>

      {/* Risk Warning */}
      <div className="border-t border-[#E0E5E0]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
          <div className="rounded-2xl border border-[#E0E5E0] bg-[#F5F7F5] p-6 sm:p-8">
            <h5 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#606862] mb-3">
              Risk Warning
            </h5>
            <p className="text-[13px] text-[#606862] leading-relaxed max-w-4xl">
              Trading in financial markets involves substantial risk of loss and is not suitable for all investors. The high degree of leverage can work against you as well as for you. Before deciding to trade, you should carefully consider your investment objectives, level of experience, and risk appetite. You should be aware of all the risks associated with trading and seek advice from an independent financial advisor if you have any doubts.
            </p>
          </div>
        </div>
      </div>

      {/* Copyright */}
      <div className="border-t border-[#E0E5E0]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-7">
          <p className="text-xs text-[#8A928C] text-center">
            © {new Date().getFullYear()} STOCKEX. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  )
}
