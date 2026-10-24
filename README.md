""" The "fat finger" safety filter:
In trading a fat finger error is when a trader accidentally adds an extra zero. 
For example, when a trader buys 1,000,000 shares instead of 100,000 and accidentally crashes a market.
We build a safety buffer for retail traders.
 Instead of tracking a pdf, we monitor a local folder where a trader saves their planned logs or excel sheets. 
 The moment the script detects a change it reads the text and sends it to the Gemma 4 api with a simple prompt
 "Look at these numbers. Are there any massive percentage jumps or weird anomalies compared to typical orders"
 And we display a clean ui. If everything seems normal it shows a green checkmark if Gemma flags any weird number jumps the screen flashes red with a safety warning
 
Right now our basic math model flags a trade if its simply 10x larger than a fixed normal size, if we have extra time we will make it dynamic. 
 The upgrade: Have our script calculate a moving average (μ) and the standard deviation (σ) of the traders last 20 trades
 The formula: Calculate a Z-Score for the incoming trade size (x):
 Z = X - Μ / Σ
 The logic:
 - If |Z| > 3. The trade is statiscally an extreme outlier ( beyond 99.7% of normal variations).
 - X represents the test statistic for the trade metric
 - M is the mean average for the trade metric being evaluated
 - Σ is the normal standard deviation for historical trade data
 """