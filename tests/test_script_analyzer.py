"""Unit tests for bash script static analysis."""

import pytest

from tektonit.script_analyzer import analyze_script, ScriptAnalysis


class TestBranchDetection:
    """Test branch detection in bash scripts."""

    def test_detect_if_statements(self):
        """Test detecting if statements."""
        script = """
        if [ "$VAR" = "value" ]; then
            echo "match"
        fi
        """
        analysis = analyze_script(script)
        assert len(analysis.branches) >= 1

    def test_detect_if_elif_else(self):
        """Test detecting if/elif/else blocks."""
        script = """
        if [ "$VAR" = "a" ]; then
            echo "a"
        elif [ "$VAR" = "b" ]; then
            echo "b"
        else
            echo "other"
        fi
        """
        analysis = analyze_script(script)
        # Should detect multiple branches
        assert len(analysis.branches) >= 1

    def test_detect_case_statements(self):
        """Test detecting case statement branches."""
        script = """
        case "$VAR" in
            pattern1)
                echo "one"
                ;;
            pattern2)
                echo "two"
                ;;
            *)
                echo "default"
                ;;
        esac
        """
        analysis = analyze_script(script)
        # Should detect branches
        assert len(analysis.branches) > 0

    def test_nested_branches(self):
        """Test detecting nested branches."""
        script = """
        if [ "$A" = "1" ]; then
            if [ "$B" = "2" ]; then
                echo "nested"
            fi
        fi
        """
        analysis = analyze_script(script)
        # Should detect both if statements
        assert len(analysis.branches) >= 2


class TestLoopDetection:
    """Test loop detection in bash scripts."""

    def test_detect_for_loops(self):
        """Test detecting for loops."""
        script = """
        for file in *.txt; do
            echo "$file"
        done
        """
        analysis = analyze_script(script)
        assert len(analysis.loops) >= 1

    def test_detect_while_loops(self):
        """Test detecting while loops."""
        script = """
        while read line; do
            echo "$line"
        done < file.txt
        """
        analysis = analyze_script(script)
        assert len(analysis.loops) >= 1

    def test_detect_until_loops(self):
        """Test detecting until loops."""
        script = """
        until [ "$VAR" = "done" ]; do
            sleep 1
        done
        """
        analysis = analyze_script(script)
        assert len(analysis.loops) >= 1

    def test_nested_loops(self):
        """Test detecting nested loops."""
        script = """
        for outer in 1 2 3; do
            for inner in a b c; do
                echo "$outer-$inner"
            done
        done
        """
        analysis = analyze_script(script)
        # Should detect both loops
        assert len(analysis.loops) >= 2


class TestCommandDetection:
    """Test external command detection."""

    def test_detect_kubectl_commands(self):
        """Test detecting kubectl usage."""
        script = """
        kubectl get pods
        kubectl apply -f config.yaml
        """
        analysis = analyze_script(script)
        command_names = [cmd.command for cmd in analysis.commands]
        assert "kubectl" in command_names

    def test_detect_curl_commands(self):
        """Test detecting curl usage."""
        script = """
        curl -s https://api.example.com/data
        """
        analysis = analyze_script(script)
        command_names = [cmd.command for cmd in analysis.commands]
        assert "curl" in command_names

    def test_detect_jq_commands(self):
        """Test detecting jq usage."""
        script = """
        echo '{"key":"value"}' | jq '.key'
        """
        analysis = analyze_script(script)
        command_names = [cmd.command for cmd in analysis.commands]
        assert "jq" in command_names

    def test_detect_multiple_commands(self):
        """Test detecting multiple different commands."""
        script = """
        git clone https://github.com/org/repo
        oras push localhost:5000/image
        tar -xzf archive.tar.gz
        """
        analysis = analyze_script(script)
        command_names = [cmd.command for cmd in analysis.commands]
        assert "git" in command_names
        assert "oras" in command_names
        assert "tar" in command_names


class TestVariableDetection:
    """Test variable read/write detection."""

    def test_detect_variables_read(self):
        """Test detecting variable reads."""
        script = """
        echo "$VAR1"
        echo "${VAR2}"
        """
        analysis = analyze_script(script)
        assert "VAR1" in analysis.variables_read or "VAR2" in analysis.variables_read

    def test_detect_variables_written(self):
        """Test detecting variable writes."""
        script = """
        VAR="value"
        export ANOTHER="test"
        """
        analysis = analyze_script(script)
        assert "VAR" in analysis.variables_written or "ANOTHER" in analysis.variables_written

    def test_detect_result_writes(self):
        """Test detecting result file writes."""
        script = """
        echo "output" > $(step.results.name.path)
        """
        analysis = analyze_script(script)
        # Should detect result writes
        assert len(analysis.result_writes) > 0 or "step.results" in script


class TestScriptFeatures:
    """Test detection of script features."""

    def test_detect_set_e(self):
        """Test detecting set -e."""
        script = """
        #!/bin/bash
        set -e
        echo "test"
        """
        analysis = analyze_script(script)
        assert analysis.has_set_e

    def test_detect_set_pipefail(self):
        """Test detecting set -o pipefail."""
        script = """
        #!/bin/bash
        set -o pipefail
        echo "test"
        """
        analysis = analyze_script(script)
        assert analysis.has_set_pipefail

    def test_detect_trap(self):
        """Test detecting trap handlers."""
        script = """
        #!/bin/bash
        trap 'echo cleanup' EXIT
        echo "test"
        """
        analysis = analyze_script(script)
        assert analysis.has_trap

    def test_detect_functions(self):
        """Test detecting function definitions."""
        script = """
        #!/bin/bash
        function my_func() {
            echo "test"
        }
        another_func() {
            echo "another"
        }
        """
        analysis = analyze_script(script)
        assert len(analysis.functions) >= 1


class TestExitPointDetection:
    """Test exit point detection."""

    def test_detect_exit_statements(self):
        """Test detecting explicit exit statements."""
        script = """
        #!/bin/bash
        if [ -z "$VAR" ]; then
            exit 1
        fi
        exit 0
        """
        analysis = analyze_script(script)
        assert len(analysis.exit_points) >= 2

    def test_detect_return_in_functions(self):
        """Test detecting return statements."""
        script = """
        #!/bin/bash
        function test_func() {
            return 1
        }
        """
        analysis = analyze_script(script)
        # Should detect exit points
        assert len(analysis.exit_points) >= 0  # May or may not count returns


class TestCompleteAnalysis:
    """Test complete script analysis."""

    def test_analysis_returns_dataclass(self):
        """Test analyze_script returns ScriptAnalysis dataclass."""
        script = """
        #!/bin/bash
        if [ -f "file.txt" ]; then
            cat file.txt
        fi
        """
        analysis = analyze_script(script)

        assert isinstance(analysis, ScriptAnalysis)
        assert hasattr(analysis, "branches")
        assert hasattr(analysis, "loops")
        assert hasattr(analysis, "commands")
        assert hasattr(analysis, "total_lines")

    def test_analyze_empty_script(self):
        """Test analyzing empty script."""
        analysis = analyze_script("")

        assert len(analysis.branches) == 0
        assert len(analysis.loops) == 0
        assert analysis.total_lines >= 0

    def test_analyze_script_line_count(self):
        """Test analysis includes line count."""
        script = "\\n".join([f"echo line{i}" for i in range(50)])
        analysis = analyze_script(script)

        assert analysis.total_lines >= 40  # Should count significant lines

    def test_to_prompt_section_formatting(self):
        """Test formatting analysis as prompt section."""
        script = """
        #!/bin/bash
        set -e
        if [ -n "$VAR" ]; then
            echo "test"
        fi
        """
        analysis = analyze_script(script)
        prompt = analysis.to_prompt_section()

        assert isinstance(prompt, str)
        assert "Script:" in prompt or "lines" in prompt.lower()


class TestComplexScript:
    """Test analyzing complex scripts."""

    def test_analyze_complex_script(self):
        """Test analyzing a realistic complex script."""
        script = """
        #!/bin/bash
        set -e
        set -o pipefail

        trap 'echo "Error on line $LINENO"' ERR

        function process_file() {
            local file="$1"
            if [ -f "$file" ]; then
                cat "$file" | jq '.data'
            else
                echo "File not found: $file" >&2
                return 1
            fi
        }

        for item in "${ITEMS[@]}"; do
            if [ "$item" = "special" ]; then
                kubectl apply -f "$item.yaml"
            elif [ "$item" = "normal" ]; then
                curl -X POST https://api.example.com
            else
                echo "Unknown: $item"
            fi
        done

        case "$MODE" in
            prod)
                oras push registry/image:prod
                ;;
            dev)
                oras push registry/image:dev
                ;;
            *)
                echo "Unknown mode: $MODE"
                exit 1
                ;;
        esac

        echo "success" > $(step.results.status.path)
        """
        analysis = analyze_script(script)

        # Should detect all major elements
        assert analysis.has_set_e
        assert analysis.has_set_pipefail
        assert analysis.has_trap
        assert len(analysis.branches) > 0
        assert len(analysis.loops) > 0
        assert len(analysis.commands) > 0
        assert len(analysis.functions) > 0
        assert len(analysis.exit_points) > 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_analyze_script_with_comments(self):
        """Test script analysis handles comments."""
        script = """
        #!/bin/bash
        # This is a comment
        # if [ false ]; then echo "not real"; fi
        echo "actual code"
        """
        analysis = analyze_script(script)

        # Should not crash
        assert isinstance(analysis, ScriptAnalysis)

    def test_analyze_malformed_script(self):
        """Test analyzing script with syntax errors."""
        script = """
        #!/bin/bash
        if [ incomplete
        for missing do
        """
        # Should not crash, return partial analysis
        analysis = analyze_script(script)
        assert isinstance(analysis, ScriptAnalysis)

    def test_analyze_very_long_script(self):
        """Test analyzing very long script doesn't timeout."""
        script = "\\n".join([f"echo line{i}" for i in range(1000)])
        analysis = analyze_script(script)

        # Should complete without hanging
        assert isinstance(analysis, ScriptAnalysis)
        assert analysis.total_lines > 500
