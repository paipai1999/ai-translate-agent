import os
from scenedetect import detect, ContentDetector, AdaptiveDetector
from brain.memory import MovieState, SceneData
from brain import config as cfg

class SceneAgent:
    def __init__(self):
        config_data = cfg.load_config()
        self.scene_threshold = config_data.get("pipeline", {}).get("scene_threshold", 27.0)
        self.min_scene_len = 15 # minimum frames per scene

    def extract_scenes(self, state: MovieState, movie_path: str) -> MovieState:
        """
        Uses PySceneDetect AdaptiveDetector to find visual camera cuts with high speed.
        Clusters these micro-scenes into macro chapters for the LLM.
        """
        print(f"[*] SceneAgent: Starting visual scene detection on {movie_path} (Threshold: {self.scene_threshold})...")
        
        try:
            # AdaptiveDetector is up to 3x faster and handles lighting changes better than ContentDetector
            scene_list = detect(movie_path, AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=self.min_scene_len), show_progress=False)
        except Exception as e:
            try:
                scene_list = detect(movie_path, ContentDetector(threshold=self.scene_threshold, min_scene_len=self.min_scene_len), show_progress=False)
            except Exception as e2:
                print(f"[ERROR] SceneAgent: PySceneDetect failed: {e2}")
                return state
            
        if not scene_list:
            print("[WARN] SceneAgent: No scenes detected.")
            return state
            
        print(f"[*] SceneAgent: Detected {len(scene_list)} raw visual scenes.")
        
        # BUG-H7 Fix: Read target_chapters from RECAP_CHAPTERS env var or pipeline config.
        # Hardcoded 10 was too many for short films and too few for 3-hour movies.
        _config_data = cfg.load_config()
        target_chapters = int(os.getenv("RECAP_CHAPTERS", "0")) or _config_data.get("pipeline", {}).get("target_chapters", 10)
        total_duration = scene_list[-1][1].get_seconds()
        # BUG-L2 Fix: Guard against zero/tiny total_duration to prevent chapter explosion
        target_chapter_len = max(1.0, total_duration / target_chapters) if target_chapters > 0 else 60.0
        
        state.timeline = []
        current_chapter_start = 0.0
        current_chapter_end = 0.0
        chapter_idx = 1
        
        for i, scene in enumerate(scene_list):
            start_sec = scene[0].get_seconds()
            end_sec = scene[1].get_seconds()
            
            # Close the current chapter if adding this scene would exceed target length 
            # (unless it's the very first scene of the chapter)
            if (end_sec - current_chapter_start) >= target_chapter_len and (current_chapter_end > current_chapter_start):
                state.timeline.append(SceneData(
                    scene_id=chapter_idx,
                    start_time=self._format_time(current_chapter_start),
                    end_time=self._format_time(current_chapter_end),
                    start_sec=current_chapter_start,
                    end_sec=current_chapter_end
                ))
                chapter_idx += 1
                current_chapter_start = current_chapter_end
            
            # Advance the chapter end to include this scene
            current_chapter_end = end_sec
            
            # If this is the last scene, close the final chapter
            if i == len(scene_list) - 1:
                state.timeline.append(SceneData(
                    scene_id=chapter_idx,
                    start_time=self._format_time(current_chapter_start),
                    end_time=self._format_time(current_chapter_end),
                    start_sec=current_chapter_start,
                    end_sec=current_chapter_end
                ))

        print(f"[*] SceneAgent: Clustered {len(scene_list)} micro-scenes into {len(state.timeline)} Macro Chapters for WriterAgent.")
        return state

    def _format_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
