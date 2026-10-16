"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { isGameUiId, GAME_META, type GameUiId } from "@/lib/games/ids";
import { GameScreen } from "@/components/games/GameScreen";
import { NumberScreen } from "@/components/games/NumberScreen";
import { BracketScreen } from "@/components/games/BracketScreen";
import { JackpotScreen } from "@/components/games/JackpotScreen";
import { PageTourAuto } from "@/components/tour/PageTourAuto";
import { tourForPath } from "@/components/tour/tours";

export default function GamePage() {
  const params = useParams();
  const slug = String(params?.slug || "");
  if (!isGameUiId(slug)) {
    return <div className="py-10 text-center text-muted-foreground">Unknown game.</div>;
  }
  const id = slug as GameUiId;
  const meta = GAME_META[id];
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
      {meta.mechanic === "updown" && <GameScreen id={id} />}
      {meta.mechanic === "number" && <NumberScreen id={id} />}
      {meta.mechanic === "bracket" && <BracketScreen id={id} />}
      {meta.mechanic === "jackpot" && <JackpotScreen id={id} />}
    </div>
  );
}
