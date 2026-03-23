from scanner.base_scanner import BaseScanner
from scanner.point_scanner.point_scanner import PointScanner
from scanner.insight_scanner.insight_scanner import InsightScanner
from common_api import CommonAPI

class FusionCoreEngine:
    def __init__(self):
        self.output_callback = None
        self.ollama_manager = None
        self.range_callback = None

        self.trace_normal = None
        self.trace_slow = None
        self.target_package = None

        self.point_scanner = PointScanner()
        self.insight_scanner = InsightScanner()

        self.common_api = None
    def start(self, ollama_manager, output_callback, range_callback=None):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.range_callback = range_callback

    def load(self, trace_normal, trace_slow, target_package):
        self.trace_normal = trace_normal
        self.trace_slow = trace_slow
        self.target_package = target_package
        self.common_api = CommonAPI(trace_normal, trace_slow, target_package)
        
        self.point_scanner.start(self.common_api, self.target_package, self.ollama_manager, self.output_callback)

        if self.range_callback:
            self.range_callback(self.point_scanner.milestone_names)

        self.insight_scanner.start(self.common_api, self.target_package, self.ollama_manager, self.output_callback)

    def run(self, output_callback=None, start_m_index=0, end_m_index=0):
        if output_callback:
            self.output_callback = output_callback
        
        self.point_scanner.milestone_start_index = start_m_index
        self.point_scanner.milestone_end_index = end_m_index
        collected_data = self.point_scanner.run(output_callback=output_callback)

        output_callback("\\token_zero")

        self.insight_scanner.collected_data = collected_data
        final_result = self.insight_scanner.run(output_callback=output_callback)
        
    def stop(self):
        pass

    def _testData(self):
            """
            Returns a mock analysis result for Insight-Scan testing.
            Content and logic are preserved from the original junior investigator report.
            """
            return {
                'milestones': {
                    'start_name': 'activityResume',
                    'end_name': 'VisualComplete',
                    'start_ts_ns': 106676020944917,
                    'end_ts_ns': 106681518444550
                },
                'target_data': {
                    'case_id': 'WC-001',
                    'target_id': 131371,
                    'duration_ms': 46.5,
                    'start_ts_ns': 106676114954292,
                    'duration_ns': 58319219,
                    'utid': 1529
                },
                'report_data': """**[Selected Slice]**
    - Case: WC-001
    - Target-Id: 131371
    - Duration: 46.5ms

    **[Detailed Reason]**
    - The top candidates per case are identified based on delta_time. In WC-001, "postAndWait" (46.5ms) and "computePalette" (0ms) are the top nodes. In WC-002, "draw-VRI[GalleryActivity]" (65.8ms) is the top node.
    - No outliers were found as none of the delta_time values are more than double the next highest in their respective cases.
    - There are no common nodes across both cases.
    - Applying the impact ratio rule, "postAndWait" in WC-001 has an impact_ratio of 0.71, which is below 0.8 but higher than others. It also meets the criteria of wait_time > self_time and wait_time >=30ms (wait_time = 0 < 30ms, so it doesn't meet this criterion).
    - Since no nodes meet all criteria, the highest average delta_time between candidates is selected: "postAndWait" in WC-001 with a delta_time of 46.5ms.

    All output must be in English only.""",
                'ai_thought': [
                    """Alright, I'm trying to figure out which optimization target to select based on the given JSON data. Let me go through each step carefully.

    First, I need to re-read the JSON and list the top 2 nodes by delta_time per case. Looking at case WC-001, the nodes are "postAndWait" with 46.5ms and "computePalette" with 0ms. So the top two are "postAndWait" and "computePalette". For case WC-002, the top node is "draw-VRI[GalleryActivity]@15e70f9" with 65.8ms, followed by "layout" with 1.4ms.

    Next, I check for outliers. An outlier is when delta_time is more than double the next highest in the same case. In WC-001, "postAndWait" is 46.5ms and the next is 0ms, so it's not an outlier. In WC-002, "draw-VRI[GalleryActivity]" is 65.8ms, and the next is 48.5ms, which isn't double, so no outliers here.

    Now, I look for common nodes across both cases. The only node present in both is "postAndWait" with 46.5ms in WC-001 and 48.5ms in WC-002. Wait, actually, looking back, "postAndWait" isn't in WC-002's tree. Hmm, maybe I made a mistake. Let me check again. In WC-002, the top node is "draw-VRI[GalleryActivity]", and its children include "postAndWait". But in WC-001, "postAndWait" is a direct child of "draw-VRI[GalleryActivity]". So they share that node but not exactly the same target_id. So maybe there's no common node.

    Since there are no common nodes, I move to the impact ratio. For WC-001, "postAndWait" has an impact_ratio of 0.71, which is below 0.8, so it doesn't qualify. The next candidate would be where wait_time > self_time and wait_time >=30ms. Looking at "computePalette" in WC-001, wait_time is 0, so it doesn't meet the criteria.

    In WC-002, "draw-VRI[GalleryActivity]" has an impact_ratio of 0.65, which is below 0.8. Its children include "postAndWait" with delta_time -1.9ms, but that's negative. The other child is "layout" with 1.4ms, which also doesn't meet the criteria.

    Since there are no nodes meeting the criteria in either case, I have to look for any candidates based on impact_ratio. In WC-001, "postAndWait" has an impact_ratio of 0.71, which is below 0.8 but higher than others. In WC-002, "draw-VRI[GalleryActivity]" has 0.65. So the highest average delta_time between them would be "postAndWait" at 46.5ms.

    Therefore, applying rule 3, I select "postAndWait" in case WC-001 with a delta_time of 46.5ms."""
                ]
            }