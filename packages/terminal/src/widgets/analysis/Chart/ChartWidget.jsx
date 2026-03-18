import Chart from '../../../components/Chart'

export default function ChartWidget({ node }) {
  return (
    <div className="h-full w-full">
      <Chart symbol="NIFTY" exchange="NSE_INDEX" />
    </div>
  )
}
