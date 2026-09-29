import unittest
from tools.altium_audit_testshim import build_intelligence

class ConnectivityIntelligenceTests(unittest.TestCase):
    def test_affinity_is_derived_without_mutation(self):
        result=build_intelligence({"nets":[
            {"name":"USB_D+","terminals":[{"designator":"J2","pin":"1"},{"designator":"U15","pin":"1"}]},
            {"name":"GND","terminals":[{"designator":"J2","pin":"2"},{"designator":"U15","pin":"2"},{"designator":"C1","pin":"2"}]},
            {"name":"MYSTERY","terminals":[{"designator":"U1","pin":"1"},{"designator":"R1","pin":"1"}]}
        ]})
        self.assertEqual(result["status"],"VERIFIED")
        self.assertEqual(result["nets"][0]["class"],"HIGH_SPEED")
        self.assertTrue(any(p["a"]=="J2" and p["b"]=="U15" for p in result["component_affinity"]))
        self.assertIn("MYSTERY", result["placement_constraints"]["unknown_intent"])

if __name__=="__main__":
    unittest.main()
