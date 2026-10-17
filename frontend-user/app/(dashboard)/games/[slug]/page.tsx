"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, CalendarOff } from "lucide-react";
import { isGameUiId, GAME_META, type GameUiId } from "@/lib/games/ids";
import { GameScreen } from "@/components/games/GameScreen";
import { NumberScreen } from "@/components/games/NumberScreen";
import { BracketScreen } from "@/components/games/BracketScreen";
import { JackpotScreen } from "@/components/games/JackpotScreen";
import { useNseClosed } from "@/components/games/useGames";
import { PageTourAuto } from "@/components/tour/PageTourAuto";
import { tourForPath } from "@/components/tour/tours";

export default function GamePage() {
  const params = useParams();
  const slug = String(params?.slug || "");
  if (!isGameUiId(slug)) {
    return <div className="py-10 text-center text-muted-foreground">Unknown game.</div>;
  }
  return <Game id={slug as GameUiId} />;
}

function Game({ id }: { id: GameUiId }) {
  const meta = GAME_META[id];
  const nseClosed = useNseClosed(id);
  // One tour per game type (Up/Down, Number, Bracket, Jackpot).
  const tourId = tourForPath(`/games/${id}`);

  return (
    <div className="space-y-4">
      {tourId && (
        <Suspense fallback={null}>
          <PageTourAuto key={tourId} id={tourId} />
        </Suspense>
      )}
      <Link href="/games" className="inline-flex items-center gap-1 text-sm font-bold text-foreground hover:opacity-80">
        <ArrowLeft className="size-4" strokeWidth={2.5} /> All games
      </Link>
      {nseClosed && <NseClosedNote />}
      {meta.mechanic === "updown" && <GameScreen id={id} />}
      {meta.mechanic === "number" && <NumberScreen id={id} />}
      {meta.mechanic === "bracket" && <BracketScreen id={id} />}
      {meta.mechanic === "jackpot" && <JackpotScreen id={id} />}
    </div>
  );
}

/** Weekend / NSE holiday: say why the NIFTY game is shut, not just "Closed". */
function NseClosedNote() {
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-[12px] leading-snug">
      <CalendarOff className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
      <span>
        <b className="text-foreground">NIFTY market is closed today.</b>{" "}
        <span className="text-muted-foreground">
          NSE is shut on weekends and holidays, so NIFTY games open again on the next trading day. BTC games run 24×7.
        </span>
      </span>
    </div>
  );
}
