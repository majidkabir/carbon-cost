package cost

import (
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// priceWithRoute is PriceWith with the route facts Calculate sets.
func priceWithRoute(res sootcase.Result, set *tariffs.Set, fd *ferries.Data, req Request, date time.Time,
	roadKm map[string]roads.Km, spans map[string][][2]float64, origin string) (Response, error) {
	req.roadKm, req.spans, req.origin = roadKm, spans, origin
	return PriceWith(res, set, fd, req, date)
}
