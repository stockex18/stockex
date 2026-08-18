import Link from 'next/link';
import { Button } from '@/components/landing/ui/button';

/** Redirects to the existing user or broker signup page (not a modal). */
export function JoinStockexSignupButton({ account, className, size, children, ...buttonProps }) {
  const href = account.signupHref || '/register';

  // `asChild` renders a single <a> wearing the button styling. Wrapping a
  // <button> in a <Link> instead puts interactive content inside the anchor,
  // which is invalid HTML and — more importantly — makes the button the
  // click target, so the link never fires.
  return (
    <Button asChild size={size} className={className} {...buttonProps}>
      <Link href={href}>{children}</Link>
    </Button>
  );
}
