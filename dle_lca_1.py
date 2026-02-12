# Initial weights
w1 = 0
w2 = 0
b = 0
learning_rate = 1

# AND gate training data
training_data = [
    (0, 0, 0),
    (0, 1, 0),
    (1, 0, 0),
    (1, 1, 1)
]

print("Initial weights:")
print("w1 =", w1, "w2 =", w2, "b =", b)
print("\nStarting Training...\n")

misclassified = 0

# One full epoch
for x1, x2, t in training_data:
    
    net = (w1 * x1) + (w2 * x2) + b
    
    if net > 0:
        y = 1
    else:
        y = 0
    
    error = t - y
    
    if error != 0:
        misclassified += 1
    
    # Update rule
    w1 = w1 + learning_rate * error * x1
    w2 = w2 + learning_rate * error * x2
    b = b + learning_rate * error
    
    print("Input:", x1, x2)
    print("Net:", net)
    print("Target:", t, "Output:", y)
    print("Updated w1 =", w1, "w2 =", w2, "b =", b)
    print("----------------------")

print("\nFinal weights after 1 epoch:")
print("w1 =", w1)
print("w2 =", w2)
print("b =", b)

# Error Percentage
total_samples = len(training_data)
error_percentage = (misclassified / total_samples) * 100

print("\nMisclassified samples:", misclassified)
print("Error Percentage:", error_percentage, "%")
N