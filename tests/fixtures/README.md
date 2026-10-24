These two JSON indexes are copied from the pinned MiniMaxAI/MiniMax-H3 revision
`42ed227ee7df40d41602854ae760620d6eb651fe` to test offline workflow routing.

Source: https://huggingface.co/MiniMaxAI/MiniMax-H3/tree/42ed227ee7df40d41602854ae760620d6eb651fe

Tests create empty weight filenames in a temporary directory only to exercise
index routing. They never load those files as weights or run model inference.
