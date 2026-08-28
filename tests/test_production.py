import unittest

from mes.production import ProductionOrder, ProductionStatus


class ProductionOrderTests(unittest.TestCase):
    def test_order_tracks_good_and_rejected_parts(self) -> None:
        order = ProductionOrder("PO-1", "Test part", 10)
        order.start()
        order.record_good(3)
        order.reject_one()
        self.assertEqual((order.total_quantity, order.good_quantity, order.rejected_quantity), (3, 2, 1))

    def test_oee_combines_availability_performance_and_quality(self) -> None:
        order = ProductionOrder("PO-2", "Test part", 10, status=ProductionStatus.RUNNING)
        order.total_quantity = 4
        order.good_quantity = 3
        order.rejected_quantity = 1
        order.elapsed_seconds = 10
        order.operating_seconds = 8
        oee = order.oee(ideal_cycle_seconds=1)
        self.assertEqual(oee["availability"], 80)
        self.assertEqual(oee["performance"], 50)
        self.assertEqual(oee["quality"], 75)
        self.assertAlmostEqual(oee["oee"], 30)

    def test_completed_order_cannot_restart(self) -> None:
        order = ProductionOrder("PO-3", "Test part", 1)
        order.start()
        order.complete()
        with self.assertRaises(ValueError):
            order.start()


if __name__ == "__main__":
    unittest.main()
