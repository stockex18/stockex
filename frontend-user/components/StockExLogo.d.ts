// Types for the JSX brand-logo module. The component itself stays .jsx
// (it's consumed by the .jsx landing components), but TypeScript callers —
// e.g. the marketing footer's brand mark — need a declaration or the import
// trips `noImplicitAny`.

export declare const STOCKEX_LOGO_SRC: string;

export declare function StockExLogo(props: {
  className?: string;
  alt?: string;
}): JSX.Element;
