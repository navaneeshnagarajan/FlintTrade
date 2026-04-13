/**
 * HomeRoute — Bento dashboard. Default route for all personas.
 * Renders a scrollable BentoGrid of persona-adaptive cards.
 *
 * Wire-up: registered as "/" inside AppLayout in main.tsx.
 */

import { BentoGrid, BentoGridContainer } from "@/components/bento/BentoGrid";
import { AddWidgetCard } from "@/components/bento/AddWidgetCard";
import { useLayoutStore } from "@/stores/layoutStore";
import { WelcomeCard } from "@/routes/home/WelcomeCard";
import { AIPulseCard } from "@/routes/home/AIPulseCard";
import { PositionsCard } from "@/routes/home/PositionsCard";
import { MiniChartCard } from "@/routes/home/MiniChartCard";
import { PortfolioCard } from "@/routes/home/PortfolioCard";
import { WatchlistCard } from "@/routes/home/WatchlistCard";
import { NewsCard } from "@/routes/home/NewsCard";
import { BreadthCard } from "@/routes/home/BreadthCard";
import { SectorCard } from "@/routes/home/SectorCard";
import { SIPCard } from "@/routes/home/SIPCard";
import { GlobalCard } from "@/routes/home/GlobalCard";
import { OrdersCard } from "@/routes/home/OrdersCard";
import StatusBar from "@/chrome/StatusBar";

export default function HomeRoute() {
  const setWidgetPickerOpen = useLayoutStore((s) => s.setWidgetPickerOpen);

  return (
    <div className="flex flex-col h-full bg-surface-base" data-testid="home-route">
      <BentoGridContainer className="flex-1 px-3 py-3">
        <BentoGrid data-testid="home-bento-grid">
          <WelcomeCard />
          <AIPulseCard />
          <PositionsCard />
          <MiniChartCard />
          <PortfolioCard />
          <WatchlistCard />
          <NewsCard />
          <BreadthCard />
          <SectorCard />
          <SIPCard />
          <GlobalCard />
          <OrdersCard />
          <AddWidgetCard onClick={() => setWidgetPickerOpen(true)} />
        </BentoGrid>
      </BentoGridContainer>

      <StatusBar cardCount={12} layoutName="Default" />
    </div>
  );
}
