import Link from 'next/link';
import { Button } from '@/components/landing/ui/button';

/** Redirects to the existing user or broker signup page (not a modal). */
export function JoinStockexSignupButton({ account, className, size, children, ...buttonProps }) {
  const href = account.signupHref || '/register';

  return (
    <Link href={href}>
      <Button size={size} className={className} {...buttonProps}>
        {children}
      </Button>
    </Link>
  );
}
