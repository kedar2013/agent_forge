import { ArrowRight, Bitcoin, Coins, LineChart, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Agent } from '../../api/types'
import Card from '../ui/Card'

type Domain = {
  key: string
  agentName: string
  title: string
  description: string
  source: string
  icon: typeof LineChart
  gradient: string
}

const DOMAINS: Domain[] = [
  {
    key: 'stocks',
    agentName: 'stock_market_analyst',
    title: 'Stocks & Indices',
    description: 'Live quotes, ticker search, and trailing returns for stocks, ETFs, and indices worldwide.',
    source: 'Yahoo Finance',
    icon: LineChart,
    gradient: 'from-blue-500 to-cyan-500',
  },
  {
    key: 'crypto',
    agentName: 'crypto_analyst',
    title: 'Crypto',
    description: 'Prices, 24h moves, market cap, and trending coins across the crypto market.',
    source: 'CoinGecko',
    icon: Bitcoin,
    gradient: 'from-amber-500 to-orange-500',
  },
  {
    key: 'forex',
    agentName: 'forex_metals_analyst',
    title: 'Forex & Metals',
    description: 'Currency exchange rates, conversions, and gold/silver/platinum/palladium spot prices.',
    source: 'Frankfurter · Gold-API',
    icon: Coins,
    gradient: 'from-emerald-500 to-teal-500',
  },
]

export default function MarketIntelligenceSection({ agents }: { agents: Agent[] | undefined }) {
  const byName = new Map((agents ?? []).map((a) => [a.name, a]))
  const orchestrator = byName.get('market_intelligence')

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-700 dark:text-slate-300">
            <Sparkles size={15} className="text-brand-500" /> Market Intelligence
          </h2>
          <p className="text-xs text-slate-400">Free, no-key market-data agents, ready to onboard</p>
        </div>
        {orchestrator && (
          <Link
            to={`/agents/${orchestrator.id}/playground`}
            className="flex items-center gap-1 rounded-md bg-gradient-to-r from-brand-600 to-accent-600 px-3 py-1.5 text-xs font-medium text-white shadow-[--shadow-glow-brand] hover:brightness-110"
          >
            Ask the orchestrator <ArrowRight size={13} />
          </Link>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {DOMAINS.map((domain) => {
          const agent = byName.get(domain.agentName)
          const Icon = domain.icon
          return (
            <Card key={domain.key} hover className="relative flex flex-col gap-3 overflow-hidden">
              <div
                className={`absolute -top-8 -right-8 h-24 w-24 rounded-full bg-gradient-to-br opacity-20 blur-2xl ${domain.gradient}`}
              />
              <div className={`w-fit rounded-lg bg-gradient-to-br p-2.5 text-white ${domain.gradient}`}>
                <Icon size={20} />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900 dark:text-slate-100">{domain.title}</h3>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{domain.description}</p>
              </div>
              <div className="mt-auto flex items-center justify-between pt-2 text-xs">
                <span className="flex items-center gap-1.5 text-slate-400">
                  <span className="h-1.5 w-1.5 animate-shimmer rounded-full bg-emerald-500" />
                  {domain.source}
                </span>
                <Link
                  to={agent ? `/agents/${agent.id}/playground` : '/agents/new'}
                  className="font-medium text-brand-600 hover:underline dark:text-brand-400"
                >
                  {agent ? 'Try it →' : 'Onboard →'}
                </Link>
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
