﻿import os
import pickle
import chess
import chess.polyglot
import numpy as np
import operator
import math

class ChessAI():
	
	def __init__(self,cache_path,model_path=None):
		# Load position cache from designated path. This is a hash-table lookup from which previously analyzed positions can be retreived.  
		self.position_cache = {}
		self.cache_path = cache_path 

		if os.path.exists(cache_path):
			file = open(cache_path,'rb')
			self.position_cache = pickle.load(file)
			file.close()

		self.piece_indices = range(1,6)
		self.null = chess.Move.null()
		self.piece_values = {1:1,2:3,3:3.3,4:4.2,5:9,6:15}
		white_piece_values = [1,3,3.3,4.2,9,15]
		black_piece_values = [-0.97*x for x in white_piece_values]
		self.piece_values = white_piece_values + black_piece_values
		self.mobility_weight = 0.1
		self.pawn_development_weight = 0.05
		self.move_entropy_weight = 0.25

		# If model_path is provided, the ML model serialized in it will be used to evaluate chess positions. Otherwise, a heuristic function will be used. 
		if model_path: 
			if os.path.exists(model_path):
				file = open(model_path,'rb')
				self.model = pickle.load(file)
				file.close()

			else:
				print('ERROR. Model not found. Please check model path again.')

	def get_entropy(self,samples):
		distribution = self.build_distribution(samples)
		product = 1.0

		for count in distribution.values():
			product = product * count

		return product
		entropy = 0.0

		for x,probability in distribution.items():
			entropy -= probability * math.log(probability)

		return entropy

	def build_distribution(self,samples):
		distribution = {}	

		for sample in samples:

			if sample not in distribution:
				distribution[sample] = 0

			distribution[sample] += 1

		#distribution = {event: count/float(len(samples)) for event,count in distribution.items()}

		return distribution

	# Count the number of all 12 piece types on the board. There are 6 pieces for each side (white and black): pawn,knight,bishop,rook,queen,king, which are defined in that order and with white chosen first. 
	def count_pieces(self,board):
		piece_counts = []
		for piece_index in self.piece_indices:
			piece_squares = board.pieces(piece_index, True)
			piece_count = len(piece_squares)
			piece_counts.append(piece_count)

		for piece_index in self.piece_indices:
			piece_squares = board.pieces(piece_index, False)
			piece_count = len(piece_squares)
			piece_counts.append(piece_count)

		return piece_counts

	# Calculate a vector containing white's move count and black's move count.
	def get_mobility_features(self,board): 
		white_mobility,black_mobility = 0,0

		if board.turn:
			white_moves = board.legal_moves
			white_mobility = white_moves.count()
			white_move_starts = self.get_move_starts(white_moves)
			white_move_entropy = self.get_entropy(white_move_starts)
			board.push(self.null)

			black_moves = board.legal_moves
			black_mobility = black_moves.count()
			black_move_starts = self.get_move_starts(black_moves)
			black_move_entropy = self.get_entropy(black_move_starts)
			board.pop()

		else:
			black_moves = board.legal_moves
			black_mobility = black_moves.count()
			black_move_starts = self.get_move_starts(black_moves)
			black_move_entropy = self.get_entropy(black_move_starts)
			board.pop()

			white_moves = board.legal_moves
			white_mobility = white_moves.count()
			white_move_starts = self.get_move_starts(white_moves)
			white_move_entropy = self.get_entropy(white_move_starts)
			board.push(self.null)

		#print(board)
		#print(white_move_entropy)
		#print(black_move_entropy)

		return [white_mobility,black_mobility,white_move_entropy,black_move_entropy]

	def get_move_starts(self,moves):
		move_starts = [move.from_square for move in moves]

		return move_starts

	# Pawn development is calculated for each player as the total amount of rows thay player's pawns have traveled. 
	def get_pawn_development(self,board):
		white_pawn_squares = board.pieces(1, True)
		white_pawn_development = sum([int(square/8) for square in white_pawn_squares])
		black_pawn_squares = board.pieces(1, False)
		black_pawn_development = sum([int(square/8) for square in black_pawn_squares])
		pawn_development = [white_pawn_development,black_pawn_development]

		return pawn_development

	# Build heuristic input features for a chess position represented by a Python chess board. 
	def get_heuristic_features(self,board):
		piece_counts = self.count_pieces(board)
		mobility_features = self.get_mobility_features(board)
		pawn_development = self.get_pawn_development(board)
		features = [piece_counts,mobility_features,pawn_development]

		return features

	# Build model-based input features for a chess position represented by a Python chess board. 
	def get_model_features(self,board):
		piece_counts = self.count_pieces(board)
		mobility = self.get_mobility(board)
		features = np.matrix(piece_counts + mobility)

		return features

	# Evaluate position using heuristics, rather than a data-driven model. 
	def heuristic_valuation(self,board):
		valuation = 0.0
		position_hash = chess.polyglot.zobrist_hash(board)

		if position_hash in self.position_cache:
			return self.position_cache[position_hash]

		piece_counts,mobility_features,pawn_development = self.get_heuristic_features(board)

		for piece_index,piece_count in enumerate(piece_counts):
			valuation += piece_count * self.piece_values[piece_index]

		valuation += (self.mobility_weight * (mobility_features[0]*mobility_features[2] - mobility_features[1]*mobility_features[3])) + (self.pawn_development_weight * (pawn_development[0] - pawn_development[1])) 
		self.position_cache[position_hash] = valuation

		return valuation

	# Evaluate position using the instance's ML model. 
	def model_valuation(self,board):
		features = (self.get_model_features(board))
		valuation = self.model.predict_proba(features)[0][1]

		return valuation

	def evaluate_move(self,board,move):
		board.push(move)
		valuation = self.heuristic_valuation(board)
		board.pop()

		return valuation

	# Algorithm for finding optimal moves in a two person, zero-sum game. It's identical to the well-known minimax algorithm, with the exception that it is keeps track of two values: alpha and beta. 
	# Alpha represents the greatest value the max player can acheive from other explored paths. Beta represents the lowest known value the minimizing player can acheive from explored
	# paths. This allows for cut-offs to be made when alpha >= beta, because in such cases, the other player is guaranteed to have a better path available, so further exploring the current node 
	# is redundant. For example, suppose you're playing a chess game and looking 4 moves ahead. When analyzing one of the possible branches, you realize that you might win if your opponent plays a
	# foolish blunder. When considering other moves your opponent could make, it's clear that there are much better ones. As soon as you figure this out, you no longer need to explore the blunder path, 
	# because assuming your opponent plays well, he/she won't do so. You can find more info online. 
	def alpha_beta_search(self,board,alpha,beta,player,depth):
		if depth == 0:
			value = self.heuristic_valuation(board)
			#value = self.model_valuation(board)
			return value

		elif player == 'White':
			for move in sorted(board.legal_moves,key=lambda move:self.evaluate_move(board,move),reverse=True):
				board.push(move)
				value = self.alpha_beta_search(board,alpha,beta,'Black',depth-1)
				board.pop()

				if value > alpha:
					alpha = value

				if alpha >= beta:
					return alpha

			return alpha

		elif player == 'Black':
			for move in sorted(board.legal_moves,key=lambda move:self.evaluate_move(board,move)):
				board.push(move)
				value = self.alpha_beta_search(board,alpha,beta,'White',depth-1)
				board.pop()

				if value < beta:
					beta = value

				if alpha >= beta:
					return beta

			return beta

	# Use an alpha beta search to determine optimal move for the given chess position. 
	def move_optimization(self,board,alpha,beta,depth):
		opt_move = ''
		min_value = 1.0e10
		for move in board.legal_moves:
			board.push(move)
			value = self.alpha_beta_search(board,alpha,beta,'White',depth-1)
			board.pop()

			if value < min_value:
				min_value = value
				opt_move = move

		self.save_position_cache()

		return opt_move

	def save_position_cache(self):
		cache_file = open(self.cache_path,'wb')
		cache_file.write(pickle.dumps(self.position_cache))
		cache_file.close()


